"""Bedrock Converse adapters for the Intervention Reasoner and the Solution Validator.

Two separate calls, prompts, response schemas, and parsers. Each accepts only a service-built
allowlisted request and returns raw model text; the service parses it with the strict schema.
No repair, coercion, retry, or fallback happens here. Provenance is stamped by the service.
"""

import asyncio
import json
import re
from typing import Callable

from pydantic import Field, ValidationError, field_validator

from app.diagnostics.bedrock import PROVIDER_NAME, _describe_type
from app.diagnostics.evidence_validator import describe_validator_converse
from app.diagnostics.models import StrictModel

from .models import InterventionType, SolutionAlignment


class InterventionError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class InterventionOutputError(InterventionError):
    """The provider returned something the application refused. Not a client fault."""


REF_PATTERN = re.compile(r"^(?:SIGNAL-001|EVID-\d{3,})$")


def _nonblank_entries(value: list[str]) -> list[str]:
    if any(not isinstance(entry, str) or not entry.strip() or len(entry) > 4000 for entry in value):
        raise ValueError("invalid list entry")
    return value


# --- Intervention Reasoner -------------------------------------------------------------

class InterventionResponse(StrictModel):
    intervention_type: InterventionType
    recommendation: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1, max_length=4000)
    target_change: str = Field(min_length=1, max_length=2000)
    fit_to_cause: str = Field(min_length=1, max_length=2000)
    evidence_reference_ids: list[str] = Field(min_length=1, max_length=100)
    limitations: list[str] = Field(max_length=50)
    missing_evidence: list[str] = Field(max_length=50)
    provider_reported_confidence: float = Field(ge=0, le=1, allow_inf_nan=False)

    @field_validator("recommendation", "rationale", "target_change", "fit_to_cause")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("blank text")
        return value

    @field_validator("limitations", "missing_evidence")
    @classmethod
    def bounded_entries(cls, value: list[str]) -> list[str]:
        return _nonblank_entries(value)


REASONER_PROMPT = """You propose what ResultsCX should actually do about one human-validated
performance diagnosis. A diagnostic reasoner proposed the diagnosis, and a human supervisor
then approved it or revised it and approved the revision. That human-validated diagnosis is
authoritative for this task: do not re-diagnose, dispute, or reinterpret its cause_domain,
performance_dimension, or observed defect. Do not recalculate, override, or reinterpret the
deterministic QA facts, and do not add statistics of your own.

Input. signal and evidence_items are deterministic QA facts. Counts and rates describe only
the criterion results that were evaluated: evaluations_containing_criterion is how many
evaluations contain this criterion and total_loaded_evaluations is the whole loaded dataset,
which may be larger. validated_diagnosis is the human-validated diagnosis: the observed
behavioral defect, cause_domain (knowledge_gap, skill_gap, process_gap, or undetermined),
performance_dimension (capability: the agent could not perform the behavior; execution: the
agent could but did not on the cited calls; undetermined), the explanation, and the evidence
it acknowledged as missing. human_validation says whether the supervisor revised the proposal
and, if so, the supervisor's stated reason. citation_roles lists the references the validated
diagnosis cited as supporting or conflicting; they are the only references you may cite.
text_coverage reports evaluator comments that exist locally but were withheld from you by
policy; absence of comment text never means no comment existed, and you must never invent,
guess, or paraphrase withheld comments.

ResultsCX reasoning standard. A performance problem does not automatically mean training is
the correct intervention. Choose the one intervention type that fits this validated cause and
this observed problem:
- training: structured instruction is warranted, typically for a knowledge gap the agent
  cannot close through practice or reminders alone.
- practice_simulation: rehearsal, simulation, or role-play with feedback, typically for a
  skill gap where the agent knows what to do but cannot yet perform it reliably.
- coaching: supervisor coaching, feedback, or reinforcement, typically when the agent has the
  capability but did not execute it on the cited calls, or when attention or habit rather
  than knowledge or skill explains the pattern.
- process_correction: a workflow, SOP, tool, system, script, or policy change, typically for
  a process gap where following the process as designed produced the failure.
- investigate_further: the validated cause is undetermined, or the evidence cannot show what
  would help; name the specific missing evidence.
These are considerations, not rules. Reason from this diagnosis and this evidence. Failure
count, failure rate, recurrence, and score rate describe what happened, not what would fix
it; frequency alone never justifies training. A high failure rate with an undetermined cause
calls for investigation, not training. Training an agent to work around a flawed process
does not correct a process gap. Approval of a diagnosis is not approval of training. State
the target plainly: the observable behavior the agent should perform, or the operational
change the organization should make. State what evidence is missing or limits your
confidence. A human reviews this proposal afterward; it is a recommendation, not a decision.
Return exactly one JSON object, no markdown or surrounding prose."""

REASONER_FIELD_GUIDANCE = {
    "intervention_type": "The single intervention type defined above.",
    "recommendation": "One concise statement of what ResultsCX should do.",
    "rationale": "Why this intervention follows from the validated diagnosis and the cited "
                 "evidence, in plain language.",
    "target_change": "The observable agent behavior to establish, or the operational change to "
                     "make. Concrete enough to recognize when it has happened.",
    "fit_to_cause": "Why this intervention type fits the validated cause_domain and "
                    "performance_dimension rather than the alternatives.",
    "evidence_reference_ids": "References copied exactly from citation_roles (supporting or "
                              "conflicting). Never invent, alter, renumber, or repeat a "
                              "reference, and never cite a reference that citation_roles does "
                              "not list. At least one entry.",
    "limitations": "Important limits of this recommendation. ALWAYS a JSON array of strings, "
                   "even for one item; use [] when there are none.",
    "missing_evidence": "Evidence that would strengthen or change the recommendation. ALWAYS a "
                        "JSON array of strings, even for one item; use [] when nothing is "
                        "missing. Must be non-empty for investigate_further.",
    "provider_reported_confidence": "ALWAYS a JSON number literal such as 0.35, never a string. "
                                    "Qualitative labels such as \"low\", \"moderate\", \"high\", "
                                    "and percentages such as \"35%\" are invalid.",
}

REASONER_SHAPE_EXAMPLE = {
    "intervention_type": InterventionType.INVESTIGATE_FURTHER.value,
    "recommendation": "string", "rationale": "string", "target_change": "string",
    "fit_to_cause": "string", "evidence_reference_ids": ["EVID-001"],
    "limitations": ["string"], "missing_evidence": ["string"],
    "provider_reported_confidence": 0.35,
}


def _contract(model, guidance: dict, example: dict, count_word: str) -> str:
    schema = model.model_json_schema()
    lines = [f"Output contract. Return exactly one raw JSON object and nothing else: no markdown, "
             f"no code fences, and no prose, labels, or comments before or after it. The object "
             f"has exactly these {count_word} keys, all required, and no other keys:"]
    for name, prop in schema["properties"].items():
        if "$ref" in prop:
            prop = schema["$defs"][prop["$ref"].rsplit("/", 1)[1]]
        lines.append(f'- "{name}": {_describe_type(prop)}. {guidance[name]}')
    lines.append("All arrays remain JSON arrays, including single entries. Confidence must be a JSON "
                 "number, never a string or qualitative label. Do not output local IDs, provider or "
                 "model metadata, timestamps, generation mode, statistics, or a diagnosis of your own. "
                 "Malformed or incoherent output is discarded without repair or retry.")
    lines.append("Shape illustration with placeholder values (copy the types, not the values):")
    lines.append(json.dumps(example))
    return "\n".join(lines)


def reasoner_contract() -> str:
    return _contract(InterventionResponse, REASONER_FIELD_GUIDANCE, REASONER_SHAPE_EXAMPLE, "nine")


REASONER_SYSTEM_PROMPT = REASONER_PROMPT + "\n\n" + reasoner_contract()


def parse_intervention_response(text: str, allowed_refs: set[str]) -> InterventionResponse:
    """Strict parse. `allowed_refs` are the references the validated diagnosis cited."""
    try:
        raw = json.loads(text)
        confidence = raw.get("provider_reported_confidence") if isinstance(raw, dict) else None
        if type(confidence) not in (int, float):
            raise ValueError("non-numeric confidence")
        result = InterventionResponse.model_validate(raw)
        refs = result.evidence_reference_ids
        if (any(not REF_PATTERN.fullmatch(ref) for ref in refs) or len(refs) != len(set(refs))
                or not set(refs) <= allowed_refs):
            raise ValueError("invalid references")
        if result.intervention_type == InterventionType.INVESTIGATE_FURTHER and not result.missing_evidence:
            raise ValueError("investigation without missing evidence")
        return result
    except (ValueError, TypeError, ValidationError, AttributeError) as exc:
        raise InterventionOutputError("invalid_intervention_output",
                                      "Intervention reasoner returned invalid output") from exc


# --- Solution Validator ----------------------------------------------------------------

class SolutionResponse(StrictModel):
    alignment_outcome: SolutionAlignment
    alignment_assessment: str = Field(min_length=1, max_length=4000)
    aligned_points: list[str] = Field(max_length=50)
    misaligned_points: list[str] = Field(max_length=50)
    unsupported_assumptions: list[str] = Field(max_length=50)
    missing_information: list[str] = Field(max_length=50)
    provider_reported_confidence: float = Field(ge=0, le=1, allow_inf_nan=False)

    @field_validator("alignment_assessment")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("blank assessment")
        return value

    @field_validator("aligned_points", "misaligned_points", "unsupported_assumptions", "missing_information")
    @classmethod
    def bounded_entries(cls, value: list[str]) -> list[str]:
        return _nonblank_entries(value)


VALIDATOR_PROMPT = """You independently review whether one proposed intervention addresses one
human-validated diagnosis. Answer only this question: does the proposed intervention logically
address the validated cause and the observed performance problem, given the evidence? Assess
the intervention only. The human-validated diagnosis is authoritative and is not under review:
never propose, suggest, or imply a replacement diagnosis, cause_domain, or
performance_dimension, and never propose a replacement intervention. Do not recalculate or
reinterpret the deterministic QA facts. This is a review of logical fit before an intervention;
do not claim it was implemented or effective, or that learner performance improved.

Input. signal and evidence_items are deterministic QA facts; counts and rates cover only the
evaluated criterion results, and total_loaded_evaluations may exceed
evaluations_containing_criterion. validated_diagnosis is the diagnosis a human supervisor
approved, or revised and approved; human_validation says which, with the supervisor's reason
for any revision. citation_roles lists the references the validated diagnosis cited.
proposed_intervention is the recommendation under review: its type, recommendation,
rationale, target_change, fit_to_cause, cited references, limitations, missing evidence, and
the reasoner's self-reported confidence. text_coverage counts evaluator comments that exist
locally but were withheld from the reasoner and from you; never invent or paraphrase them,
and treat any claim that rests on comments that were not supplied as unsupported.

Reasoning standard. A performance problem does not automatically mean training is the correct
intervention. Never equate a high failure rate with a training need, recurrence with a
knowledge gap, approval of the diagnosis with approval of training, or a supported diagnosis
with a suitable intervention. Check whether the intervention type fits the validated
cause_domain and performance_dimension: training or practice aimed at an agent for a process
gap, training for an agent who already has the capability but did not execute it, or coaching
for a knowledge gap the agent has never been taught, usually do not fit. Check whether
target_change addresses the observed behavioral defect rather than a different behavior.
Check whether the rationale rests on the cited evidence rather than on frequency alone, on
withheld comments, or on facts not supplied. Check whether the limitations and missing
evidence are honest. An investigate_further proposal for an undetermined diagnosis that names
the missing evidence is aligned; do not penalize restraint.

Outcomes. aligned: the intervention type and target change address the validated cause and
the observed problem, and the rationale rests on the evidence. partially_aligned: the
intervention addresses part of the problem, or its type fits but the target change is vague
or incomplete, or its rationale rests on assumptions the evidence does not establish.
misaligned: the intervention does not address the validated cause or the observed problem,
for example training for a process gap or training justified by frequency alone.
insufficient_evidence: the supplied information cannot determine whether the intervention
fits; name what is missing. Confidence measures how strongly the evidence supports your
outcome, not how persuasive the proposal reads. Never assert or imply human approval of the
intervention. Return exactly one JSON object, no markdown or surrounding prose."""

VALIDATOR_FIELD_GUIDANCE = {
    "alignment_outcome": "The single outcome defined above.",
    "alignment_assessment": "Plain-language reasoning for the outcome: how the proposal does or "
                            "does not address the validated cause and the observed problem.",
    "aligned_points": "Specific aspects of the proposal that address the validated diagnosis. "
                      "ALWAYS a JSON array of strings, even for one item; use [] when none. "
                      "Must be non-empty for aligned and partially_aligned.",
    "misaligned_points": "Specific aspects that do not address the validated cause or observed "
                         "problem. ALWAYS a JSON array of strings; use [] when none. Must be "
                         "empty for aligned. misaligned requires at least one entry here or in "
                         "unsupported_assumptions.",
    "unsupported_assumptions": "Assumptions the proposal makes that the evidence does not "
                               "establish, quoted or closely paraphrased. ALWAYS a JSON array of "
                               "strings; use [] when none.",
    "missing_information": "Information that would be needed to judge or improve the fit. ALWAYS "
                           "a JSON array of strings; use [] when nothing is missing. Must be "
                           "non-empty for insufficient_evidence.",
    "provider_reported_confidence": "ALWAYS a JSON number literal such as 0.35, never a string. "
                                    "Qualitative labels such as \"low\", \"moderate\", \"high\", "
                                    "and percentages such as \"35%\" are invalid.",
}

VALIDATOR_SHAPE_EXAMPLE = {
    "alignment_outcome": SolutionAlignment.PARTIALLY_ALIGNED.value,
    "alignment_assessment": "string", "aligned_points": ["string"],
    "misaligned_points": [], "unsupported_assumptions": ["string"],
    "missing_information": ["string"], "provider_reported_confidence": 0.35,
}


def validator_contract() -> str:
    return _contract(SolutionResponse, VALIDATOR_FIELD_GUIDANCE, VALIDATOR_SHAPE_EXAMPLE, "seven")


VALIDATOR_SYSTEM_PROMPT = VALIDATOR_PROMPT + "\n\n" + validator_contract()


def parse_solution_response(text: str) -> SolutionResponse:
    try:
        raw = json.loads(text)
        confidence = raw.get("provider_reported_confidence") if isinstance(raw, dict) else None
        if type(confidence) not in (int, float):
            raise ValueError("non-numeric confidence")
        result = SolutionResponse.model_validate(raw)
        # An outcome must be grounded in what the validator names: "aligned" without an aligned
        # point or with a misaligned point, "misaligned" without a misalignment or unsupported
        # assumption, and "insufficient" without a gap are incoherent and refused, not repaired.
        outcome = result.alignment_outcome
        if ((outcome == SolutionAlignment.ALIGNED and (not result.aligned_points or result.misaligned_points
                                                      or result.unsupported_assumptions)) or
                (outcome == SolutionAlignment.PARTIALLY_ALIGNED and
                 (not result.aligned_points or not (result.misaligned_points or
                                                    result.unsupported_assumptions or result.missing_information))) or
                (outcome == SolutionAlignment.MISALIGNED and not result.misaligned_points
                 and not result.unsupported_assumptions) or
                (outcome == SolutionAlignment.INSUFFICIENT_EVIDENCE and not result.missing_information)):
            raise ValueError("incoherent outcome")
        return result
    except (ValueError, TypeError, ValidationError, AttributeError) as exc:
        raise InterventionOutputError("invalid_solution_output",
                                      "Solution validator returned invalid output") from exc


# --- Converse adapters ------------------------------------------------------------------

class _ConverseAdapter:
    """One Converse call with a fixed system prompt. Subclasses fix the prompt and error code."""

    system_prompt = ""
    max_tokens = 1600
    output_error = ("invalid_intervention_output", "Intervention reasoner returned invalid output")

    def __init__(self, region: str = "us-east-1",
                 model_id: str = "global.anthropic.claude-sonnet-4-6", *, client=None,
                 diagnostic_sink: Callable[[dict], None] | None = None):
        self.region = region
        self.model_id = model_id
        self._client = client
        # Only the synthetic smoke supplies a sink. No provider text or request data is sent.
        self._diagnostic_sink = diagnostic_sink

    def _converse(self, request: dict):
        if self._client is None:
            import boto3
            from botocore.config import Config
            self._client = boto3.client("bedrock-runtime", region_name=self.region,
                                        config=Config(connect_timeout=10, read_timeout=90,
                                                      retries={"max_attempts": 2, "mode": "standard"}))
        return self._client.converse(modelId=self.model_id, system=[{"text": self.system_prompt}],
                                    messages=[{"role": "user", "content": [{"text": json.dumps(request)}]}],
                                    inferenceConfig={"maxTokens": self.max_tokens, "temperature": 0})

    async def invoke(self, request: dict) -> str:
        response = await asyncio.to_thread(self._converse, request)
        if self._diagnostic_sink is not None:
            self._diagnostic_sink(describe_validator_converse(response))
        code, message = self.output_error
        # A truncated, filtered, or guardrail-stopped turn is refused even when its text parses.
        if response.get("stopReason") != "end_turn":
            raise InterventionOutputError(code, message)
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
            if not texts or not any(text.strip() for text in texts):
                raise ValueError("Empty content")
            return "".join(texts)
        except (KeyError, TypeError, ValueError) as exc:
            raise InterventionOutputError(code, message) from exc


class BedrockInterventionReasoner(_ConverseAdapter):
    system_prompt = REASONER_SYSTEM_PROMPT
    output_error = ("invalid_intervention_output", "Intervention reasoner returned invalid output")

    async def propose(self, request: dict) -> str:
        return await self.invoke(request)


class BedrockSolutionValidator(_ConverseAdapter):
    system_prompt = VALIDATOR_SYSTEM_PROMPT
    output_error = ("invalid_solution_output", "Solution validator returned invalid output")

    async def validate(self, request: dict) -> str:
        return await self.invoke(request)


__all__ = ["PROVIDER_NAME", "BedrockInterventionReasoner", "BedrockSolutionValidator",
           "InterventionError", "InterventionOutputError", "InterventionResponse", "SolutionResponse",
           "REASONER_PROMPT", "REASONER_SYSTEM_PROMPT", "REASONER_FIELD_GUIDANCE", "REASONER_SHAPE_EXAMPLE",
           "VALIDATOR_PROMPT", "VALIDATOR_SYSTEM_PROMPT", "VALIDATOR_FIELD_GUIDANCE", "VALIDATOR_SHAPE_EXAMPLE",
           "parse_intervention_response", "parse_solution_response", "reasoner_contract", "validator_contract"]
