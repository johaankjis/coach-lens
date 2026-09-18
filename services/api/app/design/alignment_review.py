"""AWS-6 Independent Training Alignment Validator: contract, provider-safe view, strict parser.

AWS-5's `AlignmentTrace` proves that every reference in a training package exists and is
consistent (`structural_references_only`). It says nothing about meaning. AWS-6 asks one
independent question of the stored package: does each downstream design element (target
behavior, objective, activity, knowledge check, practice, rubric) actually address the
human-confirmed performance gap and the solution-validated intervention it was designed from?

The review judges alignment only. It never replaces the diagnosis, changes the intervention,
regenerates or edits the package, or claims the training was delivered or effective. Its
provider receives an allowlisted semantic view with short opaque element labels and returns a
strict JSON verdict that names elements by those labels; anything else fails closed.
"""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, ValidationError, field_validator

from app.diagnostics.models import FrozenModel, ProviderMetadata, StrictModel

from .models import DesignResult, DesignId, DesignText, MAX_ITEMS, TrainingDesign
from .service import DesignError


# --- Vocabulary ---------------------------------------------------------------------------

AlignmentOutcome = Literal["aligned", "partially_aligned", "misaligned", "insufficient_information"]
DimensionOutcome = Literal["aligned", "partially_aligned", "misaligned", "insufficient_information",
                           "not_applicable"]
DesignAlignmentStatus = Literal["design_aligned", "design_questioned"]
ALIGNMENT_OUTCOMES = ("aligned", "partially_aligned", "misaligned", "insufficient_information")

# The seven semantic links reviewed, in chain order. The knowledge-check dimension is the only
# one that may be `not_applicable`, and only when the stored package has no decision check.
DIMENSIONS = ("gap_to_target_behavior", "target_behavior_to_objective", "objective_to_activity",
              "objective_to_knowledge_check", "target_behavior_to_practice", "practice_to_rubric",
              "intervention_to_package")
KNOWLEDGE_CHECK_DIMENSION = "objective_to_knowledge_check"

ELEMENT_KINDS = ("target_behavior", "objective", "activity", "knowledge_check", "practice_scenario",
                 "practice_turn", "rubric_criterion")
# Which element kinds a dimension may name. A rubric criterion cited under the gap -> behavior
# link, for example, is an impossible reference and fails closed.
DIMENSION_ELEMENT_KINDS = {
    "gap_to_target_behavior": frozenset({"target_behavior"}),
    "target_behavior_to_objective": frozenset({"target_behavior", "objective"}),
    "objective_to_activity": frozenset({"objective", "activity"}),
    "objective_to_knowledge_check": frozenset({"objective", "knowledge_check"}),
    "target_behavior_to_practice": frozenset({"target_behavior", "practice_scenario", "practice_turn"}),
    "practice_to_rubric": frozenset({"practice_scenario", "practice_turn", "rubric_criterion"}),
    "intervention_to_package": frozenset(ELEMENT_KINDS),
}

# Fixed codes and the only message text that may reach a client for each. Provider-authored
# text never appears in an error.
ERROR_MESSAGES = {
    "alignment_review_not_found": "No alignment review has been recorded for this design",
    "alignment_validator_unavailable": "No alignment validator is configured",
    "invalid_alignment_output": "Alignment validator returned invalid output",
    "alignment_validator_failure": "Alignment validator failed",
    "alignment_privacy_blocked": "Alignment review privacy policy blocked",
    "no_training_design": "No training package exists for this design run",
    "alignment_review_not_permitted": "Alignment review requires a solution-validated AWS-4 training design",
    "alignment_review_stale": "The stored alignment review does not match the current design run",
}


class AlignmentReviewError(DesignError):
    """A fixed-code AWS-6 condition. The message is always the table text for the code."""

    def __init__(self, code: str):
        super().__init__(code, ERROR_MESSAGES[code])


class AlignmentOutputError(AlignmentReviewError):
    """The provider returned something the contract refused. Nothing is stored."""


# --- Stored contract ----------------------------------------------------------------------

class DimensionReview(FrozenModel):
    outcome: DimensionOutcome
    assessment: DesignText
    # Run-prefixed identifiers of stored AWS-5 elements, resolved locally from provider labels.
    misaligned_element_ids: tuple[DesignId, ...] = Field(default=(), max_length=MAX_ITEMS)


class AlignmentDimensions(FrozenModel):
    gap_to_target_behavior: DimensionReview
    target_behavior_to_objective: DimensionReview
    objective_to_activity: DimensionReview
    objective_to_knowledge_check: DimensionReview
    target_behavior_to_practice: DimensionReview
    practice_to_rubric: DimensionReview
    intervention_to_package: DimensionReview


class AlignmentReview(FrozenModel):
    """One immutable semantic review of one stored AWS-5 training package.

    `design_digest` binds the review to the exact package content it judged; the package
    itself is never copied here and never changed by the review.
    """

    alignment_review_id: DesignId
    run_id: DesignId
    diagnosis_id: DesignId
    intervention_id: DesignId
    solution_validation_id: DesignId
    design_digest: DesignId
    assessed: Literal["training_design_package"] = "training_design_package"
    # Restates the AWS-5 handoff so the two checks are never confused: the trace was
    # structural; this record is the semantic judgement.
    structural_trace: Literal["structural_references_only"] = "structural_references_only"
    overall_outcome: AlignmentOutcome
    design_status: DesignAlignmentStatus
    overall_assessment: DesignText
    dimensions: AlignmentDimensions
    misaligned_element_ids: tuple[DesignId, ...] = Field(default=(), max_length=MAX_ITEMS * len(DIMENSIONS))
    unsupported_assumptions: tuple[DesignText, ...] = Field(default=(), max_length=MAX_ITEMS)
    missing_information: tuple[DesignText, ...] = Field(default=(), max_length=MAX_ITEMS)
    # Self-reported by the provider. Not a calibrated probability.
    provider_reported_confidence: float = Field(ge=0, le=1)
    provider_metadata: ProviderMetadata
    created_at: datetime


def design_status_for(outcome: str) -> DesignAlignmentStatus:
    """Only an overall `aligned` verdict becomes `design_aligned`; everything else is questioned."""
    return "design_aligned" if outcome == "aligned" else "design_questioned"


def design_digest(design: TrainingDesign) -> str:
    canonical = json.dumps(design.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


# --- Provider-safe view -------------------------------------------------------------------

GAP_REFERENCE = "GAP-001"
INTERVENTION_REFERENCE = "INT-001"
REQUEST_KEYS = frozenset({"confirmed_performance_gap", "validated_intervention", "training_package"})
GAP_KEYS = frozenset({"reference", "qa_criterion", "observed_behavior", "confirmed_cause_domain",
                      "performance_dimension", "cause_explanation", "human_revised"})
INTERVENTION_KEYS = frozenset({"reference", "intervention_type", "recommendation", "target_change", "rationale"})
PACKAGE_KEYS = frozenset({"performance_context", "target_behaviors", "objectives", "activities",
                          "knowledge_checks", "practice_scenarios", "supplied_operational_context",
                          "missing_operational_details"})


@dataclass(frozen=True)
class AlignmentView:
    """What the provider sees, plus the local label registry used to resolve its answer."""

    request: dict
    # label -> (element kind, run-prefixed stored identifier)
    elements: dict[str, tuple[str, str]]
    has_knowledge_checks: bool
    design_digest: str


def build_alignment_view(result: DesignResult, qa_criterion: str) -> AlignmentView:
    """Explicit allowlist over the stored result. No model_dump of a local object.

    Sends the semantic content only: gap and intervention text, and the package's behaviors,
    objectives, activities, checks, practice turns, rubric, supplied context, and declared
    missing details. Never sends evaluator or agent names, comments, row or evaluation IDs,
    lineage, run or diagnosis IDs, AWS-4 record IDs, outcome labels, gate values, counts,
    durations, or the outline schedule. Element identifiers are reduced to their short local
    labels, which are unique within a validated package.
    """
    design = result.training_design
    if design is None:
        raise AlignmentReviewError("no_training_design")
    decision = result.intervention
    if (result.generation_mode != "provider" or result.status != "ready_for_alignment_review" or
            design.design_basis is None or
            decision.intervention_type is None or decision.recommendation is None or
            decision.target_change is None or decision.intervention_id is None or
            decision.solution_validation_id is None):
        # Review only an integrated AWS-5 package with its validated intervention.
        raise AlignmentReviewError("alignment_review_not_permitted")
    prefix = design.run_id + "/"
    elements: dict[str, tuple[str, str]] = {}

    def label(kind: str, element_id: str) -> str:
        if not element_id.startswith(prefix) or len(element_id) <= len(prefix):
            raise AlignmentReviewError("alignment_review_not_permitted")
        short = element_id[len(prefix):]
        if short in elements:
            raise AlignmentReviewError("alignment_review_not_permitted")
        elements[short] = (kind, element_id)
        return short

    def labels(known: dict[str, str], ids) -> list[str]:
        return [known[value] for value in ids]

    behaviors = {b.behavior_id: label("target_behavior", b.behavior_id) for b in design.target_behaviors}
    objectives = {o.objective_id: label("objective", o.objective_id) for o in design.objectives}
    activities = {a.activity_id: label("activity", a.activity_id) for a in design.activities}
    checks = {k.check_id: label("knowledge_check", k.check_id) for k in design.decision_checks}
    scenarios = {s.scenario_id: label("practice_scenario", s.scenario_id) for s in design.practice_scenarios}
    diagnosis = result.approved_diagnosis.diagnosis
    package = {
        "performance_context": design.performance_context,
        "target_behaviors": [{"id": behaviors[b.behavior_id], "description": b.description}
                             for b in design.target_behaviors],
        "objectives": [{"id": objectives[o.objective_id], "behavior_ids": labels(behaviors, o.behavior_ids),
                        "measurable_outcome": o.measurable_outcome, "condition": o.condition,
                        "observable_action": o.observable_action, "standard": o.standard}
                       for o in design.objectives],
        "activities": [{"id": activities[a.activity_id], "activity_type": a.activity_type, "purpose": a.purpose,
                        "instructions": a.instructions, "objective_ids": labels(objectives, a.objective_ids),
                        "expected_learner_behavior": a.expected_learner_behavior,
                        "success_indicator": a.success_indicator} for a in design.activities],
        "knowledge_checks": [{"id": checks[k.check_id], "objective_ids": labels(objectives, k.objective_ids),
                              "behavior_ids": labels(behaviors, k.behavior_ids), "situation": k.situation,
                              "question": k.question,
                              "options": [{"response": o.response, "feedback": o.feedback, "correct": o.correct}
                                          for o in k.options]} for k in design.decision_checks],
        "practice_scenarios": [{
            "id": scenarios[s.scenario_id], "title": s.title, "call_driver": s.call_driver,
            "learner_role": s.learner_role, "learner_objective": s.learner_objective,
            "opening_line": s.opening_line,
            "behavior_ids": labels(behaviors, s.behavior_ids), "objective_ids": labels(objectives, s.objective_ids),
            "activity_id": activities[s.activity_id],
            "persona": {"context": s.persona.context, "communication_style": s.persona.communication_style,
                        "emotional_state": s.persona.emotional_state, "knows": s.persona.knows,
                        "wants": s.persona.wants, "withholding": s.persona.withholding,
                        "success_response": s.persona.success_response,
                        "failure_response": s.persona.failure_response},
            "beats": [{"id": label("practice_turn", b.beat_id), "trigger": b.trigger,
                       "likely_response": b.likely_response,
                       "expected_learner_behavior": b.expected_learner_behavior,
                       "success_branch": b.success_branch, "challenge_branch": b.challenge_branch,
                       "facilitator_cue": b.facilitator_cue,
                       "behavior_ids": labels(behaviors, b.behavior_ids)} for b in s.beats],
            "escalation_expectation": s.escalation_expectation,
            "completion_criteria": list(s.completion_criteria),
            "rubric": [{"id": label("rubric_criterion", r.criterion_id), "behavior_id": behaviors[r.behavior_id],
                        "objective_id": objectives[r.objective_id], "practice_behavior": r.practice_behavior,
                        "observable_success": r.observable_success, "scoring_guidance": r.scoring_guidance}
                       for r in s.rubric]} for s in design.practice_scenarios],
        "supplied_operational_context": (list(design.design_basis.supplied_operational_context)
                                         if design.design_basis is not None else []),
        "missing_operational_details": [{"placeholder": d.placeholder, "description": d.description,
                                         "needed_for": d.needed_for} for d in design.missing_operational_details],
    }
    request = {
        "confirmed_performance_gap": {
            "reference": GAP_REFERENCE, "qa_criterion": qa_criterion,
            "observed_behavior": diagnosis.observed_behavioral_defect,
            "confirmed_cause_domain": diagnosis.cause_domain.value,
            "performance_dimension": diagnosis.performance_dimension.value,
            "cause_explanation": diagnosis.explanation,
            "human_revised": result.approved_diagnosis.human_revised},
        "validated_intervention": {
            "reference": INTERVENTION_REFERENCE, "intervention_type": decision.intervention_type,
            "recommendation": decision.recommendation, "target_change": decision.target_change,
            "rationale": decision.rationale},
        "training_package": package,
    }
    if (set(request) != REQUEST_KEYS or set(request["confirmed_performance_gap"]) != GAP_KEYS or
            set(request["validated_intervention"]) != INTERVENTION_KEYS or set(package) != PACKAGE_KEYS):
        raise AlignmentReviewError("alignment_review_not_permitted")
    return AlignmentView(request=request, elements=elements, has_knowledge_checks=bool(design.decision_checks),
                         design_digest=design_digest(design))


def request_texts(value) -> list[str]:
    """Every string in a request, for the local privacy screen before any remote call."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in request_texts(v)]
    if isinstance(value, list):
        return [s for v in value for s in request_texts(v)]
    return []


# --- Strict provider response --------------------------------------------------------------

MAX_TEXT = 4000
Label = Annotated[str, Field(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9_.-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=MAX_TEXT)]


class _Node(StrictModel):
    """No extra keys, no primitive coercion, no blank text."""

    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="after")
    @classmethod
    def no_blank_text(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("blank text")
        if isinstance(value, list) and any(isinstance(v, str) and not v.strip() for v in value):
            raise ValueError("blank list entry")
        return value


class DimensionResponse(_Node):
    outcome: DimensionOutcome
    assessment: str = Field(min_length=1, max_length=2000)
    misaligned_element_ids: list[Label] = Field(max_length=MAX_ITEMS)


class DimensionsResponse(_Node):
    gap_to_target_behavior: DimensionResponse
    target_behavior_to_objective: DimensionResponse
    objective_to_activity: DimensionResponse
    objective_to_knowledge_check: DimensionResponse
    target_behavior_to_practice: DimensionResponse
    practice_to_rubric: DimensionResponse
    intervention_to_package: DimensionResponse


class AlignmentResponse(_Node):
    overall_outcome: AlignmentOutcome
    overall_assessment: str = Field(min_length=1, max_length=MAX_TEXT)
    dimensions: DimensionsResponse
    unsupported_assumptions: list[Text] = Field(max_length=50)
    missing_information: list[Text] = Field(max_length=50)
    provider_reported_confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse_alignment_response(text: str, view: AlignmentView) -> AlignmentResponse:
    """Strict schema, reference validation against the stored package, and outcome coherence.

    Nothing is repaired: an unknown, duplicate, or impossible element reference, a
    `not_applicable` knowledge-check verdict for a package that has a check (or a verdict for
    one that has none), or an overall outcome its own dimensions contradict is refused.
    """
    try:
        raw = json.loads(text, object_pairs_hook=_unique_json_object)
        if not isinstance(raw, dict):
            raise ValueError("not an object")
        confidence = raw.get("provider_reported_confidence")
        if type(confidence) not in (int, float):
            raise ValueError("non-numeric confidence")
        result = AlignmentResponse.model_validate(raw)
    except (ValueError, TypeError, ValidationError, AttributeError) as exc:
        raise AlignmentOutputError("invalid_alignment_output") from exc
    outcomes = {}
    any_misaligned_element = False
    for name in DIMENSIONS:
        dimension: DimensionResponse = getattr(result.dimensions, name)
        ids = dimension.misaligned_element_ids
        if len(ids) != len(set(ids)):
            raise AlignmentOutputError("invalid_alignment_output")
        for element in ids:
            known = view.elements.get(element)
            if known is None or known[0] not in DIMENSION_ELEMENT_KINDS[name]:
                raise AlignmentOutputError("invalid_alignment_output")
        if dimension.outcome in ("aligned", "not_applicable") and ids:
            raise AlignmentOutputError("invalid_alignment_output")
        if name == KNOWLEDGE_CHECK_DIMENSION:
            if (dimension.outcome == "not_applicable") == view.has_knowledge_checks:
                raise AlignmentOutputError("invalid_alignment_output")
        elif dimension.outcome == "not_applicable":
            raise AlignmentOutputError("invalid_alignment_output")
        outcomes[name] = dimension.outcome
        any_misaligned_element = any_misaligned_element or bool(ids)
    applicable = [outcome for outcome in outcomes.values() if outcome != "not_applicable"]
    all_aligned = all(outcome == "aligned" for outcome in applicable)
    overall = result.overall_outcome
    # An outcome must be grounded in what the review itself names, as in AWS-4.
    if overall == "aligned" and (not all_aligned or any_misaligned_element or
                                 result.unsupported_assumptions or result.missing_information):
        raise AlignmentOutputError("invalid_alignment_output")
    if overall == "partially_aligned" and (
            "misaligned" in applicable or "insufficient_information" in applicable or
            result.missing_information or
            (all_aligned and not result.unsupported_assumptions)):
        raise AlignmentOutputError("invalid_alignment_output")
    if overall == "misaligned" and "misaligned" not in applicable:
        raise AlignmentOutputError("invalid_alignment_output")
    if overall == "insufficient_information" and ("misaligned" in applicable or
                                                   not result.missing_information):
        raise AlignmentOutputError("invalid_alignment_output")
    return result


def to_alignment_review(parsed: AlignmentResponse, result: DesignResult, view: AlignmentView,
                        provider_metadata: ProviderMetadata, created_at: datetime) -> AlignmentReview:
    """Resolve labels to stored identifiers and stamp provenance locally. Nothing here is
    provider-asserted except the verdict text, outcomes, and confidence."""
    design = result.training_design
    decision = result.intervention
    dimensions = {}
    misaligned: list[str] = []
    for name in DIMENSIONS:
        dimension: DimensionResponse = getattr(parsed.dimensions, name)
        resolved = tuple(view.elements[element][1] for element in dimension.misaligned_element_ids)
        misaligned.extend(element for element in resolved if element not in misaligned)
        dimensions[name] = DimensionReview(outcome=dimension.outcome, assessment=dimension.assessment,
                                           misaligned_element_ids=resolved)
    review_id = "alr_" + sha256(f"{design.run_id}:{view.design_digest}".encode("utf-8")).hexdigest()[:24]
    return AlignmentReview(
        alignment_review_id=review_id, run_id=design.run_id, diagnosis_id=design.diagnosis_id,
        intervention_id=decision.intervention_id, solution_validation_id=decision.solution_validation_id,
        design_digest=view.design_digest, overall_outcome=parsed.overall_outcome,
        design_status=design_status_for(parsed.overall_outcome), overall_assessment=parsed.overall_assessment,
        dimensions=AlignmentDimensions(**dimensions), misaligned_element_ids=tuple(misaligned),
        unsupported_assumptions=tuple(parsed.unsupported_assumptions),
        missing_information=tuple(parsed.missing_information),
        provider_reported_confidence=parsed.provider_reported_confidence,
        provider_metadata=provider_metadata, created_at=created_at)


__all__ = ["ALIGNMENT_OUTCOMES", "DIMENSIONS", "DIMENSION_ELEMENT_KINDS", "ELEMENT_KINDS", "ERROR_MESSAGES",
           "GAP_KEYS", "INTERVENTION_KEYS", "PACKAGE_KEYS", "REQUEST_KEYS", "KNOWLEDGE_CHECK_DIMENSION",
           "AlignmentDimensions", "AlignmentOutputError", "AlignmentResponse", "AlignmentReview",
           "AlignmentReviewError", "AlignmentView", "DimensionResponse", "DimensionReview",
           "DimensionsResponse", "build_alignment_view", "design_digest", "design_status_for",
           "parse_alignment_response", "request_texts", "to_alignment_review"]
