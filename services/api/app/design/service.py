"""One-click orchestration from the M3 approval gate to an immutable M5 result.

Three paths share one orchestration and one immutable, idempotent run:

A. Controlled fixture path. Both providers are fixtures (`controlled_fixture = True` on the
   object). Test and synthetic-demo use only; nothing here is an AI decision.
B. Integrated application path. The intervention step is the AWS-4 handoff
   (`app.interventions.handoff.ValidatedInterventionHandoff`), which reads the stored,
   solution-reviewed intervention record instead of deciding anything itself.
C. Provider-backed AWS-5 generation. A real training designer runs only on path B, and only
   when the projected decision carries a `permitted` training design gate, an `aligned`
   solution outcome, the AWS-4 identifiers, and a training or practice intervention type.
   AWS-4 is authoritative for whether design may proceed; AWS-5 only decides how.
"""

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from typing import Protocol

from app.diagnostics.engine import DiagnosticError, DiagnosticService

from .alignment import build_alignment_trace
from .models import (AWS4_VALIDATION_SOURCE, DesignInput, DesignResult, DecisionType,
                     InterventionDecision, TRAINING_INTERVENTION_TYPES)
from .validation import InvalidDesignOutput, validate_decision, validate_training


class InterventionReasoner(Protocol):
    async def decide(self, context: DesignInput) -> object: ...


class TrainingDesigner(Protocol):
    async def design(self, context: DesignInput, decision: object) -> object: ...


class DesignError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


# Design errors that pass to a client with their own code, each with the only message text
# allowed for it. Any other DesignError a provider raises is reported as a generic failure.
PASSTHROUGH_DESIGN_ERRORS = {
    "design_provider_unavailable": "No design provider is configured",
    # AWS-4 handoff preconditions (see app.interventions.handoff).
    "intervention_not_proposed": "Propose and validate an intervention before design",
    "solution_not_validated": "Validate the proposed intervention before design",
    "training_design_withheld": "Training design withheld: the solution review questioned the proposed training",
    "solution_questioned": "The solution review questioned the proposed intervention; a new reviewed proposal is required before design",
    "intervention_stale": "The stored intervention does not match the current validated diagnosis",
    # Service-side gate on provider-backed AWS-5 generation (path C above).
    "training_design_not_permitted": "Provider-backed training design requires an aligned, solution-validated AWS-4 training or practice intervention",
    # AWS-5 designer policy stop.
    "design_privacy_blocked": "Training design privacy policy blocked",
}

# The only refusal reasons a training designer may raise, each with the only message text
# that can reach a client. An unknown reason is reported as a generic provider failure.
REFUSAL_MESSAGES = {
    "not_training_intervention": "The validated intervention is not a training or practice intervention",
    "investigation_required": "The intervention requires investigation before training design",
    "solution_validation_required": "Training design requires the AWS-4 solution-validated intervention handoff",
    "training_design_not_permitted": PASSTHROUGH_DESIGN_ERRORS["training_design_not_permitted"],
    "intervention_mismatch": "The intervention does not belong to this design run",
}


class TrainingDesignRefused(DesignError):
    """A training designer declined to design because the intervention is not designable.

    The refusal is a fixed reason, never provider text. The service re-raises it with the
    fixed message for that reason so the client learns why without any provider prose.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("training_design_refused", REFUSAL_MESSAGES.get(reason, "Training design refused"))


class UnavailableDesignProvider:
    async def decide(self, context):
        raise DesignError("design_provider_unavailable", "No intervention provider is configured")

    async def design(self, context, decision):
        raise DesignError("design_provider_unavailable", "No training provider is configured")


def _provider_kind(provider: object) -> str:
    if isinstance(provider, UnavailableDesignProvider):
        return "unavailable"
    # An AWS-4 handoff adapter has no provider of its own; it classifies the installed
    # intervention reasoner object it reads from, using the same object-based rules.
    upstream = getattr(provider, "upstream_provider_kind", None)
    if callable(upstream):
        kind = upstream()
        return kind if kind in ("unavailable", "controlled_fixture") else "provider"
    return "controlled_fixture" if getattr(provider, "controlled_fixture", False) is True else "provider"


def design_provider_kind(intervention: object, training: object) -> str:
    """Classify the installed design providers from the objects, never from a label.

    Mirrors M3 `provider_kind`: a fixture must declare `controlled_fixture = True` on itself.
    Both unavailable is "unavailable"; fixtures (with or without an unavailable partner) are
    "controlled_fixture"; anything else is a real "provider", so a remote provider can never
    be reported or recorded as a non-AI fixture.
    """
    kinds = {_provider_kind(intervention), _provider_kind(training)}
    if "provider" in kinds:
        return "provider"
    if "controlled_fixture" in kinds:
        return "controlled_fixture"
    return "unavailable"


def is_aws4_handoff(intervention: object) -> bool:
    """The intervention step declares, on the object, that it projects the stored AWS-4 record."""
    return getattr(intervention, "validation_source", None) == AWS4_VALIDATION_SOURCE


def training_design_permitted(decision: InterventionDecision) -> bool:
    """AWS-4's answer to *whether* training design may run, read from the projected decision.

    Every field must be present: a fixture decision without them is not permission.
    """
    return (decision.decision_type == DecisionType.TRAINING and
            decision.intervention_type in TRAINING_INTERVENTION_TYPES and
            decision.intervention_id is not None and decision.solution_validation_id is not None and
            decision.solution_alignment == "aligned" and decision.training_design_gate == "permitted" and
            decision.recommendation is not None and decision.target_change is not None)


class DesignService:
    def __init__(self, diagnostics: DiagnosticService, intervention: InterventionReasoner,
                 training: TrainingDesigner, *, controlled_fixture: bool = False):
        # `generation_mode` on every result and `/diagnostics/mode` derive from this flag, so
        # it must agree with what the provider objects declare about themselves.
        if controlled_fixture != (design_provider_kind(intervention, training) == "controlled_fixture"):
            raise DesignError("provider_mismatch",
                              "controlled_fixture flag disagrees with the installed design providers")
        self.diagnostics = diagnostics
        self.intervention = intervention
        self.training = training
        self.controlled_fixture = controlled_fixture
        self._results: dict[str, DesignResult] = {}
        self._lock = asyncio.Lock()

    def _context(self, hypothesis_id: str) -> DesignInput:
        # The approval gate is always called, including on reads. No caller-supplied cause.
        approved = self.diagnostics.get_approved_diagnosis(hypothesis_id)
        signal = self.diagnostics.signals[approved.signal_id]
        revision = self.diagnostics.get(hypothesis_id)
        rationale = next((event.rationale for event in revision.events if event.action == "revise"), None)
        citations = (*approved.diagnosis.supporting_evidence,
                     *approved.diagnosis.conflicting_evidence)
        digest = sha256(f"{hypothesis_id}:{approved.approved_at.isoformat()}".encode()).hexdigest()[:16]
        return DesignInput(run_id=f"design_{digest}", approved=approved,
                           signal_criterion=signal.criterion,
                           signal_fail_count=signal.fail_count,
                           signal_evaluated_results=signal.evaluated_results,
                           allowed_evidence=citations, revision_rationale=rationale)

    def get(self, hypothesis_id: str) -> DesignResult:
        self._context(hypothesis_id)
        if hypothesis_id not in self._results:
            raise DesignError("design_not_found", "No design run exists for this diagnosis")
        return self._results[hypothesis_id].model_copy(deep=True)

    async def _design_training(self, context: DesignInput, decision: InterventionDecision) -> object:
        """Path C: provider-backed training generation runs only behind the AWS-4 gate.

        A controlled fixture service (path A, `generation_mode: controlled_fixture`) is exempt
        because its fixtures perform no inference; the M4 synthetic demo still feeds its
        fixture through the handoff. Any service whose result would be `generation_mode:
        provider` must be fed by the handoff object and by a decision AWS-4 marked
        `permitted`, so a fixture decision or any cause-derived route can never trigger
        provider generation. An unavailable designer keeps its own 503.
        """
        if (not self.controlled_fixture and _provider_kind(self.training) != "unavailable" and
                not (is_aws4_handoff(self.intervention) and training_design_permitted(decision))):
            raise DesignError("training_design_not_permitted",
                              PASSTHROUGH_DESIGN_ERRORS["training_design_not_permitted"])
        # Providers receive a minimized fresh copy each call; see DesignInput.provider_view.
        return await self.training.design(context.provider_view(), decision.model_copy(deep=True))

    async def run(self, hypothesis_id: str) -> DesignResult:
        context = self._context(hypothesis_id)
        async with self._lock:
            if hypothesis_id in self._results:
                return self.get(hypothesis_id)
            try:
                raw_decision = await self.intervention.decide(context.provider_view())
                decision = validate_decision(raw_decision, context)
                training = None
                if decision.decision_type == DecisionType.TRAINING:
                    raw_training = await self._design_training(context, decision)
                    training = validate_training(raw_training, context, decision=decision)
            except InvalidDesignOutput as exc:
                raise DesignError("invalid_design_output", "Design provider returned invalid output") from exc
            except DesignError as exc:
                # Only the service's own signals, the AWS-4 handoff preconditions, and a
                # fixed-reason designer refusal pass through, each reconstructed with fixed
                # text. Any other provider-raised DesignError is treated as a failure so its
                # text never reaches a client response.
                if exc.code in PASSTHROUGH_DESIGN_ERRORS:
                    raise DesignError(exc.code, PASSTHROUGH_DESIGN_ERRORS[exc.code]) from exc
                if (exc.code == "training_design_refused" and
                        getattr(exc, "reason", None) in REFUSAL_MESSAGES):
                    raise DesignError("training_design_refused", REFUSAL_MESSAGES[exc.reason]) from exc
                raise DesignError("design_provider_failure", "Design provider failed") from exc
            except Exception as exc:
                raise DesignError("design_provider_failure", "Design provider failed") from exc
            status = {DecisionType.TRAINING: "ready_for_alignment_review",
                      DecisionType.NON_TRAINING: "alternative_recommended",
                      DecisionType.INVESTIGATE: "evidence_required"}[decision.decision_type]
            result = DesignResult(run_id=context.run_id, diagnosis_id=hypothesis_id,
                                  created_at=datetime.now(timezone.utc), status=status,
                                  generation_mode="controlled_fixture" if self.controlled_fixture else "provider",
                                  approved_diagnosis=context.approved,
                                  intervention=decision, training_design=training,
                                  alignment_trace=(build_alignment_trace(training, decision)
                                                   if training is not None else None))
            self._results[hypothesis_id] = result
            return result.model_copy(deep=True)
