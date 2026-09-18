"""M5 proposed intervention and training artifacts. No learner results live here."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.diagnostics.models import (ApprovedDiagnosis, CauseDomain, EvidenceReference,
                                    FrozenModel, MAX_ID_LENGTH, MAX_LIST_LENGTH,
                                    MAX_TEXT_LENGTH, PerformanceDimension, ProviderMetadata)

DesignId = Annotated[str, Field(min_length=1, max_length=MAX_ID_LENGTH)]
DesignText = Annotated[str, Field(min_length=1, max_length=MAX_TEXT_LENGTH)]
# List bounds are storage-safety limits on untrusted provider output, like M3's.
MAX_ITEMS = MAX_LIST_LENGTH

# Placeholder substituted for the reviewer identifier in provider-facing input.
REDACTED_REVIEWER = "[reviewer]"


class DecisionType(StrEnum):
    TRAINING = "training"
    NON_TRAINING = "non_training"
    INVESTIGATE = "investigate"


class DesignInput(FrozenModel):
    run_id: DesignId
    approved: ApprovedDiagnosis
    signal_criterion: str
    signal_fail_count: int
    signal_evaluated_results: int
    # The existing M3 gate validated these citations. No raw comments or source rows cross.
    allowed_evidence: tuple[EvidenceReference, ...]
    revision_rationale: str | None = None

    def provider_view(self) -> "DesignInput":
        """Fresh copy for a provider: the reviewer identifier is not needed to design.

        Diagnosis text, missing-evidence entries, and the revision rationale still cross
        this boundary verbatim; see the M5 privacy boundary before using a remote provider.
        """
        approved = self.approved.model_copy(update={"approved_by": REDACTED_REVIEWER}, deep=True)
        return self.model_copy(update={"approved": approved}, deep=True)


class NextAction(FrozenModel):
    action_id: DesignId
    title: DesignText
    instructions: DesignText


class InterventionDecision(FrozenModel):
    run_id: DesignId
    diagnosis_id: DesignId
    decision_type: DecisionType
    rationale: DesignText
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    risks: tuple[DesignText, ...] = Field(default=(), max_length=MAX_ITEMS)
    unresolved_questions: tuple[DesignText, ...] = Field(default=(), max_length=MAX_ITEMS)
    next_actions: tuple[NextAction, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    # Provider self-identification for audit. It is not a trust signal: the service, not
    # the provider, assigns `DesignResult.generation_mode`.
    provider_metadata: ProviderMetadata


class TargetBehavior(FrozenModel):
    behavior_id: DesignId
    diagnosis_id: DesignId
    description: DesignText


class Objective(FrozenModel):
    objective_id: DesignId
    behavior_ids: tuple[DesignId, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    measurable_outcome: DesignText
    # AWS-5 optional decomposition of a measurable objective: the condition under which the
    # learner performs, the observable action, and the standard that makes it measurable.
    condition: DesignText | None = None
    observable_action: DesignText | None = None
    standard: DesignText | None = None


class Activity(FrozenModel):
    activity_id: DesignId
    activity_type: DesignText
    purpose: DesignText
    instructions: DesignText
    objective_ids: tuple[DesignId, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    expected_learner_behavior: DesignText
    success_indicator: DesignText
    duration_minutes: int = Field(gt=0, le=240)


class OutlineSection(FrozenModel):
    section_id: DesignId
    title: DesignText
    purpose: DesignText
    duration_minutes: int = Field(gt=0, le=240)
    objective_ids: tuple[DesignId, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    activity_ids: tuple[DesignId, ...] = Field(default=(), max_length=MAX_ITEMS)


class CheckOption(FrozenModel):
    option_id: DesignId
    response: DesignText
    feedback: DesignText
    correct: bool


class DecisionCheck(FrozenModel):
    check_id: DesignId
    objective_ids: tuple[DesignId, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    # Optional direct trace to target behaviors; must be reachable through the objectives.
    behavior_ids: tuple[DesignId, ...] = Field(default=(), max_length=MAX_ITEMS)
    situation: DesignText
    question: DesignText
    options: tuple[CheckOption, ...] = Field(min_length=4, max_length=4)


class Persona(FrozenModel):
    persona_id: DesignId
    name: DesignText
    context: DesignText
    communication_style: DesignText
    emotional_state: DesignText
    knows: DesignText
    wants: DesignText
    withholding: DesignText
    success_response: DesignText
    failure_response: DesignText


class ConversationBeat(FrozenModel):
    beat_id: DesignId
    trigger: DesignText
    likely_response: DesignText
    success_branch: DesignText
    challenge_branch: DesignText
    # AWS-5 scripted-practice detail: what the learner is expected to do at this turn, what the
    # facilitator or evaluator watches for, and which scenario behaviors the turn exercises.
    expected_learner_behavior: DesignText | None = None
    facilitator_cue: DesignText | None = None
    behavior_ids: tuple[DesignId, ...] = Field(default=(), max_length=MAX_ITEMS)


class RubricCriterion(FrozenModel):
    criterion_id: DesignId
    behavior_id: DesignId
    objective_id: DesignId
    practice_behavior: DesignText
    observable_success: DesignText
    scoring_guidance: DesignText


class PracticeScenario(FrozenModel):
    scenario_id: DesignId
    title: DesignText
    call_driver: DesignText
    learner_role: DesignText
    persona: Persona
    learner_objective: DesignText
    opening_line: DesignText
    behavior_ids: tuple[DesignId, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    objective_ids: tuple[DesignId, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    activity_id: DesignId
    beats: tuple[ConversationBeat, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    completion_criteria: tuple[DesignText, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    rubric: tuple[RubricCriterion, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    debrief_prompts: tuple[DesignText, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    # AWS-5 optional setup and handling expectations. `escalation_expectation` stays None when
    # no escalation procedure was supplied; the designer must not invent one.
    scenario_setup: DesignText | None = None
    escalation_expectation: DesignText | None = None


class TrainingFocus(StrEnum):
    """What the validated intervention asks training to build. Drives package requirements."""

    KNOWLEDGE = "knowledge"
    SKILL = "skill"
    KNOWLEDGE_AND_SKILL = "knowledge_and_skill"


class GapReference(FrozenModel):
    """The confirmed performance gap the design answers, copied from the approved diagnosis."""

    diagnosis_id: DesignId
    signal_id: DesignId
    observed_behavior: DesignText
    cause_domain: CauseDomain
    performance_dimension: PerformanceDimension
    human_revised: bool


class InterventionReference(FrozenModel):
    """The validated training intervention the design was generated from."""

    run_id: DesignId
    decision_type: Literal["training"]
    training_focus: TrainingFocus
    validation_source: Literal["m5_intervention_decision", "aws4_solution_validator"]
    summary: DesignText


class DesignBasis(FrozenModel):
    """Explicit gap -> intervention -> guidance references so AWS-6 can check alignment.

    Assembled locally by the designer from its validated input, never by the provider.
    """

    gap: GapReference
    intervention: InterventionReference
    guidance_version: DesignId
    supplied_operational_context: tuple[DesignText, ...] = Field(default=(), max_length=MAX_ITEMS)


class MissingOperationalDetail(FrozenModel):
    """An operational fact the design needed but was not given. Surfaced, never invented."""

    detail_id: DesignId
    placeholder: DesignText
    description: DesignText
    needed_for: DesignText


class TrainingDesign(FrozenModel):
    run_id: DesignId
    diagnosis_id: DesignId
    performance_context: DesignText
    target_behaviors: tuple[TargetBehavior, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    objectives: tuple[Objective, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    outline: tuple[OutlineSection, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    activities: tuple[Activity, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    decision_checks: tuple[DecisionCheck, ...] = Field(default=(), max_length=MAX_ITEMS)
    practice_scenarios: tuple[PracticeScenario, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    # AWS-5 additions. Both are optional so the M5 controlled fixture stays valid unchanged.
    design_basis: DesignBasis | None = None
    missing_operational_details: tuple[MissingOperationalDetail, ...] = Field(default=(), max_length=MAX_ITEMS)
    provider_metadata: ProviderMetadata


class AlignmentLink(FrozenModel):
    """One validated-gap -> intervention -> behavior -> objective -> activity -> practice -> rubric path."""

    diagnosis_id: DesignId
    intervention_run_id: DesignId
    behavior_id: DesignId
    objective_id: DesignId
    activity_id: DesignId
    scenario_id: DesignId
    criterion_id: DesignId


class KnowledgeCheckLink(FrozenModel):
    check_id: DesignId
    objective_id: DesignId
    behavior_ids: tuple[DesignId, ...] = Field(min_length=1, max_length=MAX_ITEMS)


class AlignmentTrace(FrozenModel):
    """Mechanical reference chain for the AWS-6 alignment check. Not a judgement of alignment."""

    run_id: DesignId
    diagnosis_id: DesignId
    assessment: Literal["structural_references_only"] = "structural_references_only"
    links: tuple[AlignmentLink, ...] = Field(min_length=1, max_length=MAX_ITEMS * MAX_ITEMS)
    knowledge_check_links: tuple[KnowledgeCheckLink, ...] = Field(default=(), max_length=MAX_ITEMS * MAX_ITEMS)
    missing_operational_detail_ids: tuple[DesignId, ...] = Field(default=(), max_length=MAX_ITEMS)


class DesignResult(FrozenModel):
    run_id: str
    diagnosis_id: str
    created_at: datetime
    generation_mode: Literal["provider", "controlled_fixture"]
    status: Literal["ready_for_alignment_review", "alternative_recommended", "evidence_required"]
    approved_diagnosis: ApprovedDiagnosis
    intervention: InterventionDecision
    training_design: TrainingDesign | None
    # Service-built from the validated training design; present exactly when training is.
    alignment_trace: AlignmentTrace | None = None

    @model_validator(mode="after")
    def consistent_branch(self):
        expected = {DecisionType.TRAINING: "ready_for_alignment_review",
                    DecisionType.NON_TRAINING: "alternative_recommended",
                    DecisionType.INVESTIGATE: "evidence_required"}[self.intervention.decision_type]
        if self.status != expected or (self.training_design is None) != (self.intervention.decision_type != DecisionType.TRAINING):
            raise ValueError("Intervention and result branch disagree")
        if (self.alignment_trace is None) != (self.training_design is None):
            raise ValueError("Alignment trace must accompany exactly a training design")
        if self.alignment_trace is not None and (self.alignment_trace.run_id != self.run_id or
                                                 self.alignment_trace.diagnosis_id != self.diagnosis_id):
            raise ValueError("Alignment trace provenance disagrees with the result")
        return self
