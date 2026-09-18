"""Bedrock Training Designer: a validated training intervention in, an M5 training package out.

The designer never sees QA rows, evaluator comments, names, local identifiers, lineage, or
counts. It receives the confirmed gap and validated intervention as text, the versioned
ResultsCX design guidance as instructions, and returns one strict JSON package with short
local identifiers that this module prefixes with the run ID before the M5 structural
validator runs. There is no repair, retry, or fixture fallback: anything the contract
refuses is discarded and nothing is stored.
"""

import asyncio
from datetime import datetime, timezone
import json
import re
from typing import Annotated, Callable

from pydantic import Field, ValidationError, field_validator

from app.diagnostics.bedrock import PROVIDER_NAME
from app.diagnostics.engine import remote_invocation_policy
from app.diagnostics.evidence_validator import _sensitive_diagnosis_text
from app.diagnostics.models import StrictModel

from .guidance import GUIDANCE_VERSION, guidance_text
from .intervention_input import ValidatedTrainingIntervention, training_intervention_from_decision
from .models import DecisionType, DesignInput, InterventionDecision, TrainingFocus
from .service import DesignError, TrainingDesignRefused
from .validation import InvalidDesignOutput, PLACEHOLDER_PATTERN


MAX_TEXT = 4000
MAX_ITEMS = 12  # A focused package, not a curriculum. Storage limits stay at the M5 bounds.
GAP_REFERENCE = "GAP-001"
INTERVENTION_REFERENCE = "INT-001"
ShortId = Field(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9_.-]+$")
Text = Field(min_length=1, max_length=MAX_TEXT)
ShortIdList = list[Annotated[str, Field(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9_.-]+$")]]
TextList = list[Annotated[str, Field(min_length=1, max_length=MAX_TEXT)]]
ShortIds = Field(min_length=1, max_length=MAX_ITEMS)


class _Node(StrictModel):
    @field_validator("*", mode="after")
    @classmethod
    def no_blank_text(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("blank text")
        if isinstance(value, list) and any(isinstance(v, str) and not v.strip() for v in value):
            raise ValueError("blank list entry")
        return value


class DesignerTargetBehavior(_Node):
    id: str = ShortId
    gap_reference: str = Field(min_length=1, max_length=16)
    description: str = Text


class DesignerObjective(_Node):
    id: str = ShortId
    behavior_ids: ShortIdList = ShortIds
    condition: str = Text
    observable_action: str = Text
    standard: str = Text
    measurable_outcome: str = Text


class DesignerActivity(_Node):
    id: str = ShortId
    activity_type: str = Field(min_length=1, max_length=64)
    purpose: str = Text
    instructions: str = Text
    objective_ids: ShortIdList = ShortIds
    expected_learner_behavior: str = Text
    success_indicator: str = Text
    duration_minutes: int = Field(ge=1, le=240)


class DesignerSection(_Node):
    id: str = ShortId
    title: str = Text
    purpose: str = Text
    duration_minutes: int = Field(ge=1, le=240)
    objective_ids: ShortIdList = ShortIds
    activity_ids: ShortIdList = Field(max_length=MAX_ITEMS)


class DesignerCheckOption(_Node):
    id: str = ShortId
    response: str = Text
    feedback: str = Text
    correct: bool


class DesignerKnowledgeCheck(_Node):
    id: str = ShortId
    objective_ids: ShortIdList = ShortIds
    behavior_ids: ShortIdList = ShortIds
    situation: str = Text
    question: str = Text
    options: list[DesignerCheckOption] = Field(min_length=4, max_length=4)


class DesignerPersona(_Node):
    id: str = ShortId
    name: str = Field(min_length=1, max_length=80)
    context: str = Text
    communication_style: str = Text
    emotional_state: str = Text
    knows: str = Text
    wants: str = Text
    withholding: str = Text
    success_response: str = Text
    failure_response: str = Text


class DesignerBeat(_Node):
    id: str = ShortId
    trigger: str = Text
    likely_response: str = Text
    expected_learner_behavior: str = Text
    success_branch: str = Text
    challenge_branch: str = Text
    facilitator_cue: str = Text
    behavior_ids: ShortIdList = ShortIds


class DesignerRubricCriterion(_Node):
    id: str = ShortId
    behavior_id: str = ShortId
    objective_id: str = ShortId
    practice_behavior: str = Text
    observable_success: str = Text
    scoring_guidance: str = Text


class DesignerPracticeScenario(_Node):
    id: str = ShortId
    title: str = Text
    call_driver: str = Text
    scenario_setup: str = Text
    learner_role: str = Text
    persona: DesignerPersona
    learner_objective: str = Text
    opening_line: str = Text
    behavior_ids: ShortIdList = ShortIds
    objective_ids: ShortIdList = ShortIds
    activity_id: str = ShortId
    beats: list[DesignerBeat] = Field(min_length=1, max_length=MAX_ITEMS)
    escalation_expectation: str | None = Field(default=None, max_length=MAX_TEXT)
    completion_criteria: TextList = Field(min_length=1, max_length=MAX_ITEMS)
    rubric: list[DesignerRubricCriterion] = Field(min_length=1, max_length=MAX_ITEMS)
    debrief_prompts: TextList = Field(min_length=1, max_length=MAX_ITEMS)


class DesignerMissingDetail(_Node):
    id: str = ShortId
    placeholder: str = Field(min_length=1, max_length=120)
    description: str = Text
    needed_for: str = Text


class DesignerResponse(_Node):
    performance_context: str = Text
    target_behaviors: list[DesignerTargetBehavior] = Field(min_length=1, max_length=MAX_ITEMS)
    objectives: list[DesignerObjective] = Field(min_length=1, max_length=MAX_ITEMS)
    outline: list[DesignerSection] = Field(min_length=1, max_length=MAX_ITEMS)
    activities: list[DesignerActivity] = Field(min_length=1, max_length=MAX_ITEMS)
    knowledge_checks: list[DesignerKnowledgeCheck] = Field(max_length=MAX_ITEMS)
    practice_scenarios: list[DesignerPracticeScenario] = Field(min_length=1, max_length=MAX_ITEMS)
    missing_operational_details: list[DesignerMissingDetail] = Field(max_length=MAX_ITEMS)


DESIGN_PROMPT = """You are the CoachLens Training Designer for a healthcare contact-center partner.
You receive one confirmed performance gap and one validated training intervention, and you
produce one focused ResultsCX-aligned training package: observable target behaviors,
measurable objectives, a concise outline, proposed activities, decision-based knowledge
checks, and a scripted hands-on practice simulation with a scoring rubric.

Design from the confirmed gap and the validated intervention only. Do not rediagnose, do not
propose a different cause, and do not widen the training beyond that gap. Every target
behavior cites the gap reference. Every objective names at least one target behavior. Every
activity and outline section names objectives. Every knowledge check and practice scenario
names objectives and behaviors. Every rubric criterion names a behavior and an objective that
itself covers that behavior. Every target behavior must be exercised by at least one practice
scenario and scored by at least one rubric criterion. Every activity must appear in exactly one
outline section, and a section's activities may only cover that section's objectives.

You were given no QA statistics, comments, or records. Do not state or imply counts, rates,
percentages, scores, or how many calls failed. Do not describe evaluator comments. The member
persona is fictional: a first name only, no real person, no protected health information.

Supplied operational context is the complete set of operational facts you may rely on. If a
policy, escalation path, contact, system step, benefit rule, or clinical fact would be needed
and is not listed there, write a token of the form [PLACEHOLDER:M1] in the text where it
belongs and declare M1 in missing_operational_details with the same placeholder string. Set
escalation_expectation to null unless escalation handling was supplied. Never invent such
facts to make the package look complete.

training_focus meaning: knowledge needs at least one knowledge check; skill needs a practice
scenario with at least two conversational turns that each state the expected learner
behavior; knowledge_and_skill needs both. Every focus needs at least one practice scenario.
Identifiers are short local labels (B1, O1, S1, A1, K1, K1_OPT1, P1, PERSONA1, BEAT1, R1, M1),
unique across the whole package. Return exactly one JSON object and nothing else."""

# Rules the schema cannot express, keyed by field name or "Model.field" for the specific case.
FIELD_GUIDANCE = {
    "id": "Short local label, unique across the whole package.",
    "performance_context": "Plain-language statement of the confirmed gap and what this package "
                           "trains, without numbers.",
    "gap_reference": f'Always exactly "{GAP_REFERENCE}".',
    "description": "The observable behavior a facilitator can see or hear the learner do.",
    "condition": "The circumstances under which the learner performs (for example, during a "
                 "simulated member call about a benefit question).",
    "observable_action": "What the learner does, stated as an observable action.",
    "standard": "The measurable criterion for meeting the objective, expressed as observable "
                "completeness or accuracy, not as a QA statistic.",
    "measurable_outcome": "One sentence combining condition, observable action, and standard.",
    "activity_type": "One of: demonstration, guided_practice, decision_drill, simulation, debrief, "
                     "or another short label.",
    "instructions": "What the facilitator and learner do, step by step.",
    "expected_learner_behavior": "What the learner is expected to do, observably.",
    "success_indicator": "What shows the activity achieved its purpose.",
    "activity_ids": "Activities scheduled in this section; each activity appears in exactly one section.",
    "situation": "A realistic situation that requires a decision.",
    "question": "The decision the learner must make.",
    "options": "Exactly four options with exactly one correct.",
    "response": "The option text.",
    "feedback": "Why this specific option is or is not the right decision. Must differ across the "
                "four options and must not repeat the option text.",
    "correct": "true for exactly one option per check.",
    "name": "A fictional first name only.",
    "scenario_setup": "What the facilitator sets up before the simulation begins.",
    "learner_role": "The role the learner plays.",
    "opening_line": "The persona's first words to the learner.",
    "trigger": "What the learner has just done or said that this turn responds to.",
    "likely_response": "What the persona says at this turn.",
    "DesignerBeat.expected_learner_behavior": "What the learner should do at this turn, observably.",
    "success_branch": "How the persona responds if the learner performs the expected behavior.",
    "challenge_branch": "How the persona responds if the learner does not.",
    "facilitator_cue": "What the facilitator or evaluator watches or listens for at this turn.",
    "escalation_expectation": "JSON null unless escalation handling was supplied in the operational context.",
    "completion_criteria": "Observable conditions that end the simulation successfully.",
    "practice_behavior": "The target behavior as performed in this practice.",
    "observable_success": "What competent performance looks like, observably.",
    "scoring_guidance": "How an evaluator decides met versus not met.",
    "debrief_prompts": "Questions the facilitator asks after the simulation.",
    "placeholder": "The exact token used in the text, of the form [PLACEHOLDER:M1].",
    "DesignerMissingDetail.description": "The operational fact that was needed and not supplied.",
    "needed_for": "Which part of the package needs it.",
    "knowledge_checks": "Required (at least one) for knowledge and knowledge_and_skill focus.",
    "missing_operational_details": "One entry per placeholder token used. [] when none were needed.",
}


def _resolve(prop: dict, defs: dict) -> dict:
    if "$ref" in prop:
        return defs[prop["$ref"].rsplit("/", 1)[1]]
    if "anyOf" in prop:  # `str | None`
        options = [_resolve(option, defs) for option in prop["anyOf"]]
        nullable = any(option.get("type") == "null" for option in options)
        base = next(option for option in options if option.get("type") != "null")
        return {**base, "nullable": nullable} if nullable else base
    return prop


def _type_text(prop: dict) -> str:
    kind = prop.get("type")
    null = " or JSON null" if prop.get("nullable") else ""
    if kind == "string":
        bounds = f" of {prop.get('minLength', 0)} to {prop['maxLength']} characters" if "maxLength" in prop else ""
        return f"JSON string{bounds}{null}"
    if kind == "integer":
        low = prop.get("minimum", prop.get("exclusiveMinimum", 0) + 1)
        return f"JSON integer from {low} to {prop['maximum']}"
    if kind == "boolean":
        return "JSON boolean"
    if kind == "array":
        return f"JSON array of {prop.get('minItems', 0)} to {prop['maxItems']} items"
    if kind == "object":
        return "JSON object"
    raise TypeError(f"Unsupported response field type: {kind}")


def _describe(name: str, prop: dict, defs: dict, model: str, indent: int) -> list[str]:
    prop = _resolve(prop, defs)
    pad = "  " * indent
    guidance = FIELD_GUIDANCE.get(f"{model}.{name}", FIELD_GUIDANCE.get(name, ""))
    lines = [f'{pad}- "{name}": {_type_text(prop)}. {guidance}'.rstrip()]
    if prop.get("type") == "array":
        items = _resolve(prop["items"], defs)
        if items.get("type") == "object":
            lines[-1] += f" Each item is a JSON object with exactly these {len(items['properties'])} keys:"
            lines.extend(_describe_object(items, defs, indent + 1))
        else:
            lines[-1] += f" Each item is a {_type_text(items)}."
    elif prop.get("type") == "object":
        lines[-1] += f" Exactly these {len(prop['properties'])} keys:"
        lines.extend(_describe_object(prop, defs, indent + 1))
    return lines


def _describe_object(schema: dict, defs: dict, indent: int) -> list[str]:
    return [line for name, prop in schema["properties"].items()
            for line in _describe(name, prop, defs, schema.get("title", ""), indent)]


def response_contract() -> str:
    """The exact output contract rendered from the DesignerResponse schema.

    Types, bounds, and nesting come from the validator itself so the prompt cannot drift
    from what local validation accepts. Rules a schema cannot state are in FIELD_GUIDANCE.
    """
    schema = DesignerResponse.model_json_schema()
    lines = ["Output contract. Return exactly one JSON object and nothing else: no markdown, no "
             "code fences, and no prose before or after it. All keys are required at every level, "
             "arrays stay arrays even with one item, and no other keys may appear. The top-level "
             f"object has exactly these {len(schema['properties'])} keys:"]
    lines.extend(_describe_object(schema, schema.get("$defs", {}), 0))
    lines.append("Do not include run IDs, diagnosis IDs, provider or model names, generation mode, "
                 "timestamps, statistics, or any key not listed. A package that violates any rule is "
                 "discarded without repair, so a smaller valid package is better than a larger invalid one.")
    return "\n".join(lines)


SYSTEM_PROMPT = DESIGN_PROMPT + "\n\n" + guidance_text() + "\n\n" + response_contract()

# The only keys a Converse request may carry. Tests assert against these.
REQUEST_KEYS = frozenset({"design_guidance_version", "confirmed_performance_gap",
                          "validated_intervention", "supplied_operational_context"})
GAP_KEYS = frozenset({"reference", "qa_criterion", "observed_behavior", "confirmed_cause_domain",
                      "performance_dimension", "cause_explanation", "human_revised"})
INTERVENTION_KEYS = frozenset({"reference", "training_focus", "summary"})
REMOTE_POLICIES_PERMITTED = frozenset({"local_fixture", "synthetic_only", "real_minimized"})
_PERCENT_PATTERN = re.compile(r"\d\s*%|\bpercent(?:age)?\b", re.IGNORECASE)
_COUNT_PATTERN = re.compile(r"\b\d+\s+(?:of|out of)\s+\d+\s+(?:calls?|evaluations?|results?|"
                            r"interactions?|reviews?|qa)\b", re.IGNORECASE)


def build_designer_request(intervention: ValidatedTrainingIntervention, qa_criterion: str) -> dict:
    """Explicit allowlist. No model_dump of a local object, no IDs, no counts, no evidence rows."""
    request = {
        "design_guidance_version": GUIDANCE_VERSION,
        "confirmed_performance_gap": {
            "reference": GAP_REFERENCE, "qa_criterion": qa_criterion,
            "observed_behavior": intervention.confirmed_gap,
            "confirmed_cause_domain": intervention.cause_domain.value,
            "performance_dimension": intervention.performance_dimension.value,
            "cause_explanation": intervention.cause_explanation,
            "human_revised": intervention.human_revised},
        "validated_intervention": {
            "reference": INTERVENTION_REFERENCE,
            "training_focus": intervention.training_focus.value,
            "summary": intervention.intervention_summary},
        "supplied_operational_context": list(intervention.operational_context),
    }
    if (set(request) != REQUEST_KEYS or set(request["confirmed_performance_gap"]) != GAP_KEYS or
            set(request["validated_intervention"]) != INTERVENTION_KEYS):
        raise DesignError("invalid_design_input", "Design request projection drifted from allowlist")
    return request


def parse_designer_response(text: str, focus: TrainingFocus) -> DesignerResponse:
    """Strict schema plus the ResultsCX package rules that the schema cannot express."""
    try:
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise ValueError("not an object")
        result = DesignerResponse.model_validate(raw)
    except (ValueError, TypeError, ValidationError) as exc:
        raise InvalidDesignOutput("Training designer returned an invalid package") from exc
    ids = [b.id for b in result.target_behaviors] + [o.id for o in result.objectives]
    ids += [s.id for s in result.outline] + [a.id for a in result.activities]
    ids += [k.id for k in result.knowledge_checks] + [d.id for d in result.missing_operational_details]
    for check in result.knowledge_checks:
        ids.extend(option.id for option in check.options)
        if sum(option.correct for option in check.options) != 1:
            raise InvalidDesignOutput("Knowledge check needs exactly one correct option")
    for scenario in result.practice_scenarios:
        ids.append(scenario.id)
        ids.append(scenario.persona.id)
        ids.extend(beat.id for beat in scenario.beats)
        ids.extend(criterion.id for criterion in scenario.rubric)
    if len(ids) != len(set(ids)):
        raise InvalidDesignOutput("Package identifiers must be unique")
    if any(behavior.gap_reference != GAP_REFERENCE for behavior in result.target_behaviors):
        raise InvalidDesignOutput("Target behavior must cite the supplied gap reference")
    if focus in (TrainingFocus.KNOWLEDGE, TrainingFocus.KNOWLEDGE_AND_SKILL) and not result.knowledge_checks:
        raise InvalidDesignOutput("Knowledge focus requires a knowledge check")
    if focus in (TrainingFocus.SKILL, TrainingFocus.KNOWLEDGE_AND_SKILL) and not any(
            len(scenario.beats) >= 2 for scenario in result.practice_scenarios):
        raise InvalidDesignOutput("Skill focus requires a scripted practice with at least two turns")
    texts = _all_strings(raw)
    if any(_PERCENT_PATTERN.search(value) for value in texts) or _COUNT_PATTERN.search(result.performance_context):
        raise InvalidDesignOutput("Training designer may not state QA statistics")
    declared = {detail.placeholder for detail in result.missing_operational_details}
    if any(not PLACEHOLDER_PATTERN.fullmatch(p) for p in declared) or len(declared) != len(result.missing_operational_details):
        raise InvalidDesignOutput("Missing operational details need distinct placeholder tokens")
    return result


def _all_strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _all_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _all_strings(v)]
    return []


def to_training_design(response: DesignerResponse, intervention: ValidatedTrainingIntervention,
                       provider_metadata: dict) -> dict:
    """Prefix every local label with the run ID and attach the locally built design basis."""
    run = intervention.run_id
    pid = lambda label: f"{run}/{label}"  # noqa: E731
    pids = lambda labels: [pid(label) for label in labels]  # noqa: E731
    return {
        "run_id": run, "diagnosis_id": intervention.diagnosis_id,
        "performance_context": response.performance_context,
        "target_behaviors": [{"behavior_id": pid(b.id), "diagnosis_id": intervention.diagnosis_id,
                              "description": b.description} for b in response.target_behaviors],
        "objectives": [{"objective_id": pid(o.id), "behavior_ids": pids(o.behavior_ids),
                        "measurable_outcome": o.measurable_outcome, "condition": o.condition,
                        "observable_action": o.observable_action, "standard": o.standard}
                       for o in response.objectives],
        "outline": [{"section_id": pid(s.id), "title": s.title, "purpose": s.purpose,
                     "duration_minutes": s.duration_minutes, "objective_ids": pids(s.objective_ids),
                     "activity_ids": pids(s.activity_ids)} for s in response.outline],
        "activities": [{"activity_id": pid(a.id), "activity_type": a.activity_type, "purpose": a.purpose,
                        "instructions": a.instructions, "objective_ids": pids(a.objective_ids),
                        "expected_learner_behavior": a.expected_learner_behavior,
                        "success_indicator": a.success_indicator, "duration_minutes": a.duration_minutes}
                       for a in response.activities],
        "decision_checks": [{"check_id": pid(k.id), "objective_ids": pids(k.objective_ids),
                             "behavior_ids": pids(k.behavior_ids), "situation": k.situation,
                             "question": k.question,
                             "options": [{"option_id": pid(o.id), "response": o.response,
                                          "feedback": o.feedback, "correct": o.correct} for o in k.options]}
                            for k in response.knowledge_checks],
        "practice_scenarios": [{
            "scenario_id": pid(p.id), "title": p.title, "call_driver": p.call_driver,
            "learner_role": p.learner_role, "scenario_setup": p.scenario_setup,
            "persona": {"persona_id": pid(p.persona.id), "name": p.persona.name, "context": p.persona.context,
                        "communication_style": p.persona.communication_style,
                        "emotional_state": p.persona.emotional_state, "knows": p.persona.knows,
                        "wants": p.persona.wants, "withholding": p.persona.withholding,
                        "success_response": p.persona.success_response,
                        "failure_response": p.persona.failure_response},
            "learner_objective": p.learner_objective, "opening_line": p.opening_line,
            "behavior_ids": pids(p.behavior_ids), "objective_ids": pids(p.objective_ids),
            "activity_id": pid(p.activity_id),
            "beats": [{"beat_id": pid(b.id), "trigger": b.trigger, "likely_response": b.likely_response,
                       "expected_learner_behavior": b.expected_learner_behavior,
                       "success_branch": b.success_branch, "challenge_branch": b.challenge_branch,
                       "facilitator_cue": b.facilitator_cue, "behavior_ids": pids(b.behavior_ids)}
                      for b in p.beats],
            "escalation_expectation": p.escalation_expectation,
            "completion_criteria": list(p.completion_criteria),
            "rubric": [{"criterion_id": pid(r.id), "behavior_id": pid(r.behavior_id),
                        "objective_id": pid(r.objective_id), "practice_behavior": r.practice_behavior,
                        "observable_success": r.observable_success, "scoring_guidance": r.scoring_guidance}
                       for r in p.rubric],
            "debrief_prompts": list(p.debrief_prompts)} for p in response.practice_scenarios],
        "design_basis": {
            "gap": {"diagnosis_id": intervention.diagnosis_id, "signal_id": intervention.signal_id,
                    "observed_behavior": intervention.confirmed_gap,
                    "cause_domain": intervention.cause_domain.value,
                    "performance_dimension": intervention.performance_dimension.value,
                    "human_revised": intervention.human_revised},
            "intervention": {"run_id": run, "decision_type": DecisionType.TRAINING.value,
                             "training_focus": intervention.training_focus.value,
                             "validation_source": intervention.validation_source,
                             "summary": intervention.intervention_summary},
            "guidance_version": GUIDANCE_VERSION,
            "supplied_operational_context": list(intervention.operational_context)},
        "missing_operational_details": [{"detail_id": pid(d.id), "placeholder": d.placeholder,
                                         "description": d.description, "needed_for": d.needed_for}
                                        for d in response.missing_operational_details],
        # `generation_mode` is deliberately absent: the service stamps it from the object.
        "provider_metadata": provider_metadata,
    }


def converse_text(response: object) -> str:
    """Only a normally completed turn with text content may become a package."""
    if not isinstance(response, dict) or response.get("stopReason") != "end_turn":
        raise InvalidDesignOutput("Training designer returned an invalid package")
    try:
        blocks = response["output"]["message"]["content"]
        if not isinstance(blocks, list):
            raise ValueError("Unexpected content")
        texts = []
        for block in blocks:
            if not isinstance(block, dict) or len(block) != 1:
                raise ValueError("Unexpected content")
            if "text" in block and isinstance(block["text"], str):
                texts.append(block["text"])
            elif "reasoningContent" not in block:
                raise ValueError("Unexpected content")
        if not any(text.strip() for text in texts):
            raise ValueError("Empty content")
        return "".join(texts)
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidDesignOutput("Training designer returned an invalid package") from exc


class BedrockTrainingDesigner:
    """Converse adapter implementing the M5 `TrainingDesigner` protocol.

    Remote invocation is gated on the installed diagnostic reasoner's declared policy and on a
    local screen of the free text against known identifiers and comments, following AWS-3.
    Without a bound diagnostic service nothing is sent.
    """

    def __init__(self, region: str = "us-east-1",
                 model_id: str = "global.anthropic.claude-sonnet-4-6", *, client=None,
                 diagnostics=None, operational_context: tuple[str, ...] = (),
                 diagnostic_sink: Callable[[dict], None] | None = None):
        self.region = region
        self.model_id = model_id
        self._client = client
        self._diagnostics = diagnostics
        self._operational_context = tuple(operational_context)
        self._diagnostic_sink = diagnostic_sink

    def prepare(self, context: DesignInput, decision: InterventionDecision
                ) -> tuple[ValidatedTrainingIntervention, dict]:
        """Adapt, gate, screen, and project. Raises before any client exists on refusal."""
        intervention = training_intervention_from_decision(context, decision,
                                                           operational_context=self._operational_context)
        if self._diagnostics is None or remote_invocation_policy(
                self._diagnostics.reasoner) not in REMOTE_POLICIES_PERMITTED:
            raise DesignError("design_privacy_blocked", "Training design privacy policy blocked")
        request = build_designer_request(intervention, context.signal_criterion)
        if _sensitive_diagnosis_text(self._diagnostics, [request["confirmed_performance_gap"]["observed_behavior"],
                                                         request["confirmed_performance_gap"]["cause_explanation"],
                                                         request["validated_intervention"]["summary"],
                                                         *request["supplied_operational_context"]]):
            raise DesignError("design_privacy_blocked", "Training design privacy policy blocked")
        return intervention, request

    def _converse(self, request: dict):
        if self._client is None:
            import boto3
            from botocore.config import Config
            self._client = boto3.client("bedrock-runtime", region_name=self.region,
                                        config=Config(connect_timeout=10, read_timeout=240,
                                                      retries={"max_attempts": 2, "mode": "standard"}))
        return self._client.converse(modelId=self.model_id, system=[{"text": SYSTEM_PROMPT}],
                                    messages=[{"role": "user", "content": [{"text": json.dumps(request)}]}],
                                    inferenceConfig={"maxTokens": 8000, "temperature": 0})

    async def design(self, context: DesignInput, decision: InterventionDecision) -> object:
        intervention, request = self.prepare(context, decision)
        try:
            response = await asyncio.to_thread(self._converse, request)
        except Exception as exc:
            raise DesignError("design_provider_failure", "Design provider failed") from exc
        if self._diagnostic_sink is not None:
            from app.diagnostics.evidence_validator import describe_validator_converse
            self._diagnostic_sink(describe_validator_converse(response))
        parsed = parse_designer_response(converse_text(response), intervention.training_focus)
        request_id = response.get("ResponseMetadata", {}).get("RequestId")
        if not isinstance(request_id, str) or len(request_id) > 128:
            request_id = None
        metadata = {"provider": PROVIDER_NAME, "model": self.model_id, "invocation_region": self.region,
                    "invocation_id": request_id, "generated_at": datetime.now(timezone.utc)}
        return to_training_design(parsed, intervention, metadata)


__all__ = ["BedrockTrainingDesigner", "DesignerResponse", "SYSTEM_PROMPT", "REQUEST_KEYS",
           "build_designer_request", "parse_designer_response", "to_training_design",
           "response_contract", "converse_text", "TrainingDesignRefused"]
