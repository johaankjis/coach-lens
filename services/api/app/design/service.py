"""One-click orchestration from the M3 approval gate to an immutable M5 result."""

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from typing import Protocol

from app.diagnostics.engine import DiagnosticError, DiagnosticService

from .models import DesignInput, DesignResult, DecisionType
from .validation import InvalidDesignOutput, validate_decision, validate_training


class InterventionReasoner(Protocol):
    async def decide(self, context: DesignInput) -> object: ...


class TrainingDesigner(Protocol):
    async def design(self, context: DesignInput, decision: object) -> object: ...


class DesignError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class UnavailableDesignProvider:
    async def decide(self, context):
        raise DesignError("design_provider_unavailable", "No intervention provider is configured")

    async def design(self, context, decision):
        raise DesignError("design_provider_unavailable", "No training provider is configured")


class DesignService:
    def __init__(self, diagnostics: DiagnosticService, intervention: InterventionReasoner,
                 training: TrainingDesigner, *, controlled_fixture: bool = False):
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

    async def run(self, hypothesis_id: str) -> DesignResult:
        context = self._context(hypothesis_id)
        async with self._lock:
            if hypothesis_id in self._results:
                return self.get(hypothesis_id)
            try:
                # Providers receive a minimized fresh copy each call; see DesignInput.provider_view.
                raw_decision = await self.intervention.decide(context.provider_view())
                decision = validate_decision(raw_decision, context)
                training = None
                if decision.decision_type == DecisionType.TRAINING:
                    raw_training = await self.training.design(context.provider_view(),
                                                              decision.model_copy(deep=True))
                    training = validate_training(raw_training, context)
            except InvalidDesignOutput as exc:
                raise DesignError("invalid_design_output", "Design provider returned invalid output") from exc
            except DesignError as exc:
                # Only the service's own "not configured" signal passes through. Any other
                # provider-raised DesignError is treated as a failure so its text never
                # reaches a client response.
                if exc.code == "design_provider_unavailable":
                    raise
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
                                  intervention=decision, training_design=training)
            self._results[hypothesis_id] = result
            return result.model_copy(deep=True)
