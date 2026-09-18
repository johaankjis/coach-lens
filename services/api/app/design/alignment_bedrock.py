"""Bedrock Converse adapter for the AWS-6 Training Alignment Validator.

One independent call with the AWS-1/AWS-3/AWS-4/AWS-5 contract: Bedrock Runtime `Converse`,
one system prompt, one user text block, temperature 0, strict JSON, `end_turn` required, no
repair, retry, coercion, or fallback. The adapter returns raw model text; the service parses
it with the strict contract in `alignment_review.py`. Provenance is stamped by the service.
Remote invocation is gated on the bound diagnostic service's declared policy and on the AWS-3
local text screen, exactly as the AWS-5 designer gates its own call.
"""

import asyncio
import json
from typing import Callable

from app.diagnostics.bedrock import PROVIDER_NAME
from app.diagnostics.engine import remote_invocation_policy
from app.diagnostics.evidence_validator import _sensitive_diagnosis_text, describe_validator_converse

from .alignment_review import (AlignmentOutputError, AlignmentResponse, AlignmentReviewError,
                               DIMENSIONS, request_texts)


REMOTE_POLICIES_PERMITTED = frozenset({"local_fixture", "synthetic_only", "real_minimized"})

ALIGNMENT_PROMPT = """You are the CoachLens Training Alignment Validator for a healthcare
contact-center partner. You independently review whether one generated training package
actually addresses one human-confirmed performance gap and the validated intervention it was
designed from. Answer only that question.

Input. confirmed_performance_gap is the diagnosis a human supervisor confirmed: the QA
criterion, the observed behavior, the confirmed cause domain and performance dimension, and
the explanation. validated_intervention is the intervention a separate review already found
aligned with that cause: its type, recommendation, target change, and rationale.
training_package is the generated design under review: its performance context, target
behaviors, objectives, activities, knowledge checks, practice scenarios with scripted turns
and a scoring rubric, the operational context the designer was given, and the operational
details it declared missing rather than invented. Elements carry short labels such as B1, O1,
A1, K1, P1, BEAT1, and R1. Refer to elements only by those labels, exactly as given, and only
to labels that appear in the package.

The confirmed gap and the validated intervention are authoritative and are not under review.
Never rediagnose, never propose a different cause or intervention, and never rewrite, replace,
add, or remove target behaviors, objectives, activities, checks, scenarios, or rubric criteria;
describe what does not fit and leave the change to a human. Never claim the training was
delivered, was effective, or improved performance. A separate structural check already proved
that the package's references are consistent; do not repeat it and do not treat consistent
references as alignment. Judge meaning: a package can reference every element correctly and
still train the wrong behavior, for example a documentation worksheet for a gap in explaining
resolution options.

Review these seven dimensions:
1. gap_to_target_behavior: would performing each target behavior actually correct the
   confirmed performance problem?
2. target_behavior_to_objective: would meeting each objective demonstrate its target behavior?
3. objective_to_activity: does each activity teach or practice the objectives it names?
4. objective_to_knowledge_check: does each knowledge check assess the judgment its objectives
   and behaviors require, rather than unrelated recall? Use not_applicable only when the
   package contains no knowledge check.
5. target_behavior_to_practice: does each practice scenario, turn by turn, require the learner
   to perform the target behaviors?
6. practice_to_rubric: does each rubric criterion score the behavior the learner is meant to
   demonstrate in that practice?
7. intervention_to_package: taken together, does the package implement the validated
   intervention's recommendation and target change, and nothing else?

Outcomes, for each dimension and overall. aligned: the downstream meaning supports the
upstream need. partially_aligned: part supports it and part drifts, or it is too vague to be
sure it does. misaligned: it addresses a different behavior or problem. insufficient_information:
the supplied material cannot settle the question; name what is missing. Name every element
that drifts in that dimension's misaligned_element_ids. An operational fact the package relies
on that neither the gap, the intervention, nor the supplied operational context establishes is
an unsupported assumption; a declared [PLACEHOLDER] is not. Overall aligned requires every
applicable dimension aligned, no misaligned elements, and no unsupported assumptions or missing
information; overall misaligned requires at least one misaligned dimension; overall
insufficient_information requires missing_information and no misaligned dimension. Overall
partially_aligned requires a partially aligned dimension or an unsupported assumption, and no
misaligned or insufficient dimension or missing information. Confidence measures how strongly
the supplied material supports
your outcome, not how polished the package reads. Never assert or imply human approval of the
package. Return exactly one JSON object, no markdown or surrounding prose."""

FIELD_GUIDANCE = {
    "overall_outcome": "The single overall outcome defined above.",
    "overall_assessment": "Plain-language reasoning for the overall outcome: how the package does or "
                          "does not address the confirmed gap and the validated intervention.",
    "dimensions": "One entry per dimension, all seven required.",
    "outcome": "The outcome for this dimension. not_applicable is valid only for "
               "objective_to_knowledge_check when the package has no knowledge check.",
    "assessment": "Plain-language reasoning for this dimension.",
    "misaligned_element_ids": "Labels of package elements that drift in this dimension, copied exactly. "
                              "ALWAYS a JSON array of strings; use [] when none, and [] whenever the "
                              "outcome is aligned or not_applicable. Never invent, alter, or repeat a label.",
    "unsupported_assumptions": "Operational or factual assumptions the package relies on that the gap, the "
                               "intervention, and the supplied operational context do not establish. "
                               "ALWAYS a JSON array of strings; use [] when none.",
    "missing_information": "Information that would be needed to judge alignment. ALWAYS a JSON array "
                           "of strings; use [] when nothing is missing. Must be non-empty for "
                           "insufficient_information.",
    "provider_reported_confidence": "ALWAYS a JSON number literal such as 0.35, never a string. "
                                    "Qualitative labels such as \"low\", \"moderate\", \"high\", and "
                                    "percentages such as \"35%\" are invalid.",
}

SHAPE_EXAMPLE = {
    "overall_outcome": "partially_aligned", "overall_assessment": "string",
    "dimensions": {name: {"outcome": "aligned", "assessment": "string", "misaligned_element_ids": []}
                   for name in DIMENSIONS},
    "unsupported_assumptions": ["string"], "missing_information": [], "provider_reported_confidence": 0.35,
}
SHAPE_EXAMPLE["dimensions"]["objective_to_activity"] = {
    "outcome": "misaligned", "assessment": "string", "misaligned_element_ids": ["A1"]}


def _resolve(prop: dict, defs: dict) -> dict:
    if "$ref" in prop:
        return defs[prop["$ref"].rsplit("/", 1)[1]]
    return prop


def _type_text(prop: dict) -> str:
    if "enum" in prop:
        return "JSON string, exactly one of " + ", ".join(f'"{value}"' for value in prop["enum"])
    kind = prop.get("type")
    if kind == "string":
        return f"JSON string of {prop.get('minLength', 0)} to {prop['maxLength']} characters"
    if kind == "number":
        return f"JSON number from {prop['minimum']} to {prop['maximum']} inclusive"
    if kind == "array":
        return f"JSON array of {prop.get('minItems', 0)} to {prop['maxItems']} JSON strings"
    if kind == "object":
        return "JSON object"
    raise TypeError(f"Unsupported response field type: {kind}")


def _describe(name: str, prop: dict, defs: dict, indent: int) -> list[str]:
    prop = _resolve(prop, defs)
    pad = "  " * indent
    lines = [f'{pad}- "{name}": {_type_text(prop)}. {FIELD_GUIDANCE.get(name, "")}'.rstrip()]
    if prop.get("type") == "object":
        children = prop["properties"]
        refs = {child.get("$ref") for child in children.values()}
        if len(children) > 1 and len(refs) == 1 and None not in refs:
            # Every child shares one schema: name the keys once and describe the shape once.
            lines[-1] += (f" Exactly these {len(children)} keys: " + ", ".join(f'"{key}"' for key in children) +
                          ". Each is a JSON object with exactly these keys:")
            shape = _resolve(next(iter(children.values())), defs)
            for child, child_prop in shape["properties"].items():
                lines.extend(_describe(child, child_prop, defs, indent + 1))
        else:
            lines[-1] += f" Exactly these {len(children)} keys:"
            for child, child_prop in children.items():
                lines.extend(_describe(child, child_prop, defs, indent + 1))
    return lines


def response_contract() -> str:
    """The exact output contract rendered from the AlignmentResponse schema, so the prompt
    cannot drift from what local validation accepts."""
    schema = AlignmentResponse.model_json_schema()
    defs = schema.get("$defs", {})
    lines = ["Output contract. Return exactly one raw JSON object and nothing else: no markdown, no code "
             "fences, and no prose, labels, or comments before or after it. All keys are required at every "
             f"level and no other keys may appear. The top-level object has exactly these {len(schema['properties'])} keys:"]
    for name, prop in schema["properties"].items():
        lines.extend(_describe(name, prop, defs, 0))
    lines.append("All arrays remain JSON arrays, including single entries. Confidence must be a JSON number, "
                 "never a string or qualitative label. Do not output run IDs, diagnosis IDs, provider or model "
                 "metadata, timestamps, generation mode, a status, statistics, a diagnosis of your own, or any "
                 "rewritten or replacement design content. Malformed or incoherent output is discarded without "
                 "repair or retry.")
    lines.append("Shape illustration with placeholder values (copy the types, not the values):")
    lines.append(json.dumps(SHAPE_EXAMPLE))
    return "\n".join(lines)


SYSTEM_PROMPT = ALIGNMENT_PROMPT + "\n\n" + response_contract()


def converse_text(response: object) -> str:
    """Only a normally completed turn with text content may become a review."""
    if not isinstance(response, dict) or response.get("stopReason") != "end_turn":
        raise AlignmentOutputError("invalid_alignment_output")
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
        raise AlignmentOutputError("invalid_alignment_output") from exc


class BedrockAlignmentValidator:
    """Converse adapter implementing the AWS-6 `AlignmentValidatorProvider` protocol.

    Without a bound diagnostic service whose reasoner declares a permitted policy, nothing is
    sent. The request text (gap, intervention, and generated package) is screened locally
    against known names, identifiers, filenames, sheets, and verbatim comments before the call.
    """

    def __init__(self, region: str = "us-east-1",
                 model_id: str = "global.anthropic.claude-sonnet-4-6", *, client=None,
                 diagnostics=None, diagnostic_sink: Callable[[dict], None] | None = None):
        self.region = region
        self.model_id = model_id
        self._client = client
        self._diagnostics = diagnostics
        # Only the synthetic smoke supplies a sink. No provider text or request data is sent.
        self._diagnostic_sink = diagnostic_sink

    def prepare(self, request: dict) -> None:
        """Gate and screen. Raises before any client exists."""
        if self._diagnostics is None or remote_invocation_policy(
                self._diagnostics.reasoner) not in REMOTE_POLICIES_PERMITTED:
            raise AlignmentReviewError("alignment_privacy_blocked")
        if _sensitive_diagnosis_text(self._diagnostics, request_texts(request)):
            raise AlignmentReviewError("alignment_privacy_blocked")

    def _converse(self, request: dict):
        if self._client is None:
            import boto3
            from botocore.config import Config
            self._client = boto3.client("bedrock-runtime", region_name=self.region,
                                        config=Config(connect_timeout=10, read_timeout=120,
                                                      retries={"max_attempts": 2, "mode": "standard"}))
        return self._client.converse(modelId=self.model_id, system=[{"text": SYSTEM_PROMPT}],
                                    messages=[{"role": "user", "content": [{"text": json.dumps(request)}]}],
                                    inferenceConfig={"maxTokens": 4000, "temperature": 0})

    async def review(self, request: dict) -> str:
        self.prepare(request)
        try:
            response = await asyncio.to_thread(self._converse, request)
        except Exception as exc:
            raise AlignmentReviewError("alignment_validator_failure") from exc
        if self._diagnostic_sink is not None:
            self._diagnostic_sink(describe_validator_converse(response))
        return converse_text(response)


__all__ = ["ALIGNMENT_PROMPT", "FIELD_GUIDANCE", "PROVIDER_NAME", "REMOTE_POLICIES_PERMITTED", "SHAPE_EXAMPLE",
           "SYSTEM_PROMPT", "BedrockAlignmentValidator", "converse_text", "response_contract"]
