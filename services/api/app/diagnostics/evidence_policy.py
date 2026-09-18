"""Local AWS-2 preparation. This is data minimization, not PHI detection.

The free-text policy is a narrow permitted-content rule, not a detector: text crosses only
when it is short Latin-script prose with no digits or symbols, every recorded employee name
(whole name and each name part) is suppressed, and no honorific or unexplained capitalized
word remains. Every uncertain case fails closed to BLOCK. Sentence-initial unknown names,
names written in lowercase, and health terms without an identifier are not detected.
"""

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
import re
import unicodedata

from app.results_cx.models import Evaluation, SourceLineage

from .engine import ProviderOutputError
from .models import REDACTED, EvidenceBundle, redact_known_identities


class TextDecision(StrEnum):
    ALLOW_MINIMIZED = "allow_minimized"
    BLOCK = "block"
    NO_TEXT = "no_text"
    # Local text existed and the minimizer would have admitted it, but real evaluator text
    # is not transmitted in the current milestone. Distinct from BLOCK so local accounting
    # does not misreport why the text stayed home.
    WITHHELD = "withheld"


# Deliberate default for the first merged real-data path: structured ResultsCX evidence
# crosses; minimized evaluator comments do not. There is no setting, environment variable,
# or request field behind this. Activating real text is a separate reviewed code change that
# passes `transmit_minimized_text=True` from the reasoner, after the policy has been
# evaluated locally against the actual dataset.
TRANSMIT_REAL_MINIMIZED_TEXT = False


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


MAX_TEXT_LENGTH = 1000
# Everything outside this set blocks: digits, @, slashes, brackets (so source text cannot
# impersonate the suppression marker), control and format characters, non-Latin script,
# emoji, and non-ASCII whitespace. This is deliberately a permit list, never a deny list.
_PERMITTED_PUNCTUATION = frozenset(" .,;:!?'\"()-‘’“”–—")
# Tokens that indicate a third party is being named; blocked in any case or position.
_HONORIFICS = frozenset({"mr", "mrs", "ms", "mx", "dr"})
# The only capitalized words permitted after a sentence start. Everything else capitalized
# mid-sentence is treated as a possible proper noun (member, relative, clinician, facility,
# place, month, brand) and blocks the whole comment.
_PERMITTED_CAPITALIZED = frozenset({
    "I", "AGENT", "AGENTS", "MEMBER", "MEMBERS", "CALLER", "CALLERS", "CUSTOMER", "CUSTOMERS",
    "PATIENT", "PATIENTS", "PROVIDER", "PROVIDERS", "REP", "CSR", "QA", "TL", "DOB", "ID",
    "SSN", "MRN", "PHI", "PII", "HIPAA", "EOB", "PCP", "IVR", "OK"})
_SENTENCE_END = frozenset(".!?")
# A period directly followed by a letter is a domain or file reference, never prose.
_DOTTED_REFERENCE = re.compile(r"\.[^\W\d_]", re.UNICODE)
_LETTER_RUN = re.compile(r"[^\W\d_]+", re.UNICODE)
_WORD = re.compile(r"\w", re.UNICODE)
_MIN_PART_LENGTH = 2
_MIN_RESIDUAL_PART_LENGTH = 5


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value)


def _permitted_character(char: str) -> bool:
    if char in _PERMITTED_PUNCTUATION:
        return True
    return char.isalpha() and unicodedata.name(char, "").startswith("LATIN")


def identity_parts(identities: set[str]) -> set[str]:
    """Casefolded whole name and letter-run parts of every recorded employee name."""
    parts = set()
    for identity in identities:
        if identity and identity.strip():
            normalized = _normalize(identity)
            parts.update(part.casefold() for part in _LETTER_RUN.findall(normalized)
                         if len(part) >= _MIN_PART_LENGTH)
    return parts


def _redact_parts(text: str, parts: set[str]) -> str:
    return _LETTER_RUN.sub(lambda match: REDACTED if match.group().casefold() in parts else match.group(), text)


def _sentence_initial(text: str, start: int) -> bool:
    before = text[:start].rstrip(" \"'()‘’“”-")
    return not before or before[-1] in _SENTENCE_END


def _capitalization_permitted(text: str) -> bool:
    for match in _LETTER_RUN.finditer(text):
        token = match.group()
        if token.casefold() in _HONORIFICS:
            return False
        if not token[0].isupper() or len(token) == 1:
            continue
        if token.upper() in _PERMITTED_CAPITALIZED or _sentence_initial(text, match.start()):
            continue
        return False
    return True


def minimize_text(value: str | None, known_identifiers: set[str]) -> TextResult:
    if value is None or not value.strip():
        return TextResult(TextDecision.NO_TEXT)
    text = _normalize(value).strip()
    if (len(text) > MAX_TEXT_LENGTH or not all(_permitted_character(char) for char in text) or
            _DOTTED_REFERENCE.search(text)):
        return TextResult(TextDecision.BLOCK)
    identities = {_normalize(term).strip() for term in known_identifiers if term and term.strip()}
    parts = identity_parts(identities)
    minimized = _redact_parts(redact_known_identities(text, identities), parts).strip()
    residual = minimized.replace(REDACTED, " ").casefold()
    if (not _WORD.search(residual) or
            any(term.casefold() in residual for term in identities) or
            any(part in residual for part in parts if len(part) >= _MIN_RESIDUAL_PART_LENGTH) or
            not _capitalization_permitted(minimized)):
        return TextResult(TextDecision.BLOCK)
    return TextResult(TextDecision.ALLOW_MINIMIZED, minimized)


def _criterion_label(value: str, identifiers: set[str]) -> str:
    # Question wording is also untrusted workbook text. Withhold it if the narrow policy
    # cannot admit it without modification. All source wording remains local.
    result = minimize_text(value, identifiers)
    return value if result.decision == TextDecision.ALLOW_MINIMIZED and result.text == value.strip() \
        else "[criterion withheld]"


def population_digest(evaluations: list[Evaluation]) -> str:
    """Content fingerprint of a whole population, so same-ID content substitution is visible."""
    canonical = json.dumps([evaluation.model_dump(mode="json") for evaluation in evaluations],
                           sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def prepare_real_evidence(bundle: EvidenceBundle, evaluations: list[Evaluation], *,
                          transmit_minimized_text: bool = TRANSMIT_REAL_MINIMIZED_TEXT) -> ProviderSafeEvidenceBundle:
    """Prepare one M3 bundle from the trusted local population; never serialize raw models.

    Every comment still receives a local minimizer decision so coverage is exact. Text is
    copied to the wire only for ALLOW_MINIMIZED and only when `transmit_minimized_text` is
    true; otherwise the decision is recorded as WITHHELD and counted with blocked text.
    """
    from .bedrock import provider_safe_payload

    identities = {value for evaluation in evaluations for value in
                  (evaluation.agent_name, evaluation.qa_name, evaluation.team_leader) if value}
    # The structured projection contains only allowlisted fields and fresh references.
    payload, lookup = provider_safe_payload(bundle.provider_view(identities))
    criterion = _criterion_label(bundle.signal.criterion, identities)
    payload["signal"]["criterion"] = criterion
    local_references = {}
    decisions = {}
    allowed = not_transmitted = no_text = 0
    for number, item in enumerate(bundle.items, 1):
        ref = f"EVID-{number:03d}"
        wire = payload["evidence_items"][number - 1]
        wire["criterion"] = criterion
        result = minimize_text(item.evaluator_feedback, identities)
        decision = result.decision
        if decision == TextDecision.ALLOW_MINIMIZED and not transmit_minimized_text:
            decision = TextDecision.WITHHELD
        decisions[ref] = decision
        local_references[ref] = LocalEvidenceReference(item.item_id, item.evaluation_id,
                                                       item.source_lineage.model_copy(deep=True))
        if decision == TextDecision.ALLOW_MINIMIZED:
            wire["diagnostic_text"] = {"kind": "minimized_evaluator_feedback", "text": result.text}
            allowed += 1
        elif decision in (TextDecision.BLOCK, TextDecision.WITHHELD):
            not_transmitted += 1
        else:
            no_text += 1
    # `text_items_blocked` on the wire means "local text existed and was not transmitted",
    # whether the minimizer refused it or the milestone default withheld it.
    coverage = {"total_evidence_items": len(bundle.items),
                "evidence_items_with_feedback": bundle.signal.feedback_count,
                "minimized_text_items_allowed": allowed, "text_items_blocked": not_transmitted,
                "text_items_with_no_text": no_text}
    if allowed + not_transmitted + no_text != len(bundle.items):
        raise ProviderOutputError("invalid_provider_input", "Diagnostic text coverage is inconsistent")
    payload["text_coverage"] = coverage
    return ProviderSafeEvidenceBundle(payload, lookup, local_references, decisions)
