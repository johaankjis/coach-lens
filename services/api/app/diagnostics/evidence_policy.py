"""Local AWS-2 preparation. This is data minimization, not PHI detection."""

from dataclasses import dataclass
from enum import StrEnum
import re

from app.results_cx.models import Evaluation, SourceLineage

from .engine import ProviderOutputError
from .models import EvidenceBundle, redact_known_identities


class TextDecision(StrEnum):
    ALLOW_MINIMIZED = "allow_minimized"
    BLOCK = "block"
    NO_TEXT = "no_text"


@dataclass(frozen=True)
class TextResult:
    decision: TextDecision
    text: str | None = None


@dataclass(frozen=True)
class LocalEvidenceReference:
    item_id: str
    evaluation_id: str
    source_lineage: SourceLineage


@dataclass(frozen=True)
class ProviderSafeEvidenceBundle:
    payload: dict
    lookup: dict[str, tuple[str, str | None]]
    local_references: dict[str, LocalEvidenceReference]
    text_decisions: dict[str, TextDecision]


# Block obvious structured identifiers and text that is too complex for this narrow policy.
# These patterns are deliberately incomplete and make no PHI-free claim.
_HIGH_RISK = re.compile(r"\d|@|https?://|www\.|[/\\]|[\x00-\x1f\x7f]", re.IGNORECASE)
_WORD = re.compile(r"\w", re.UNICODE)


def minimize_text(value: str | None, known_identifiers: set[str]) -> TextResult:
    if value is None or not value.strip():
        return TextResult(TextDecision.NO_TEXT)
    if len(value) > 1000 or _HIGH_RISK.search(value):
        return TextResult(TextDecision.BLOCK)
    minimized = redact_known_identities(value, known_identifiers).strip()
    if (not _WORD.search(minimized.replace("[redacted]", "")) or
            any(term.strip() and term.casefold() in minimized.casefold()
                for term in known_identifiers if len(term.strip()) > 2)):
        return TextResult(TextDecision.BLOCK)
    return TextResult(TextDecision.ALLOW_MINIMIZED, minimized)


def _criterion_label(value: str, identifiers: set[str]) -> str:
    # Question wording is also untrusted workbook text. Withhold it if the narrow policy
    # cannot admit it without modification. All source wording remains local.
    result = minimize_text(value, identifiers)
    return value if result.decision == TextDecision.ALLOW_MINIMIZED and result.text == value.strip() \
        else "[criterion withheld]"


def prepare_real_evidence(bundle: EvidenceBundle, evaluations: list[Evaluation]) -> ProviderSafeEvidenceBundle:
    """Prepare one M3 bundle from the trusted local population; never serialize raw models."""
    from .bedrock import provider_safe_payload

    identities = {value for evaluation in evaluations for value in
                  (evaluation.agent_name, evaluation.qa_name, evaluation.team_leader) if value}
    # The structured projection contains only allowlisted fields and fresh references.
    payload, lookup = provider_safe_payload(bundle.provider_view(identities))
    criterion = _criterion_label(bundle.signal.criterion, identities)
    payload["signal"]["criterion"] = criterion
    local_references = {}
    decisions = {}
    allowed = blocked = no_text = 0
    for number, item in enumerate(bundle.items, 1):
        ref = f"EVID-{number:03d}"
        wire = payload["evidence_items"][number - 1]
        wire["criterion"] = criterion
        result = minimize_text(item.evaluator_feedback, identities)
        decisions[ref] = result.decision
        local_references[ref] = LocalEvidenceReference(item.item_id, item.evaluation_id,
                                                       item.source_lineage.model_copy(deep=True))
        if result.decision == TextDecision.ALLOW_MINIMIZED:
            wire["diagnostic_text"] = {"kind": "minimized_evaluator_feedback", "text": result.text}
            allowed += 1
        elif result.decision == TextDecision.BLOCK:
            blocked += 1
        else:
            no_text += 1
    coverage = {"total_evidence_items": len(bundle.items),
                "evidence_items_with_feedback": bundle.signal.feedback_count,
                "minimized_text_items_allowed": allowed, "text_items_blocked": blocked,
                "text_items_with_no_text": no_text}
    if allowed + blocked + no_text != len(bundle.items):
        raise ProviderOutputError("invalid_provider_input", "Diagnostic text coverage is inconsistent")
    payload["text_coverage"] = coverage
    return ProviderSafeEvidenceBundle(payload, lookup, local_references, decisions)
