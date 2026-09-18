"""Deterministic evidence, untrusted provider boundary, and human review."""

from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import threading
from typing import Protocol

from pydantic import BaseModel, ValidationError

from app.results_cx.models import Evaluation
from app.results_cx.pipeline import analyze

from .models import (ApprovedDiagnosis, DiagnosticHypothesis, DiagnosticRecord,
                     EvidenceBundle, EvidenceItem, EvidenceReference, HumanRevision,
                     PerformanceSignal, ProviderEvidenceBundle, ReviewEvent)


class DiagnosticError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ProviderOutputError(DiagnosticError):
    """The reasoning provider returned something the application refused. Not a client fault."""


SIGNAL_REFERENCE = "signal"  # The only aggregate citation; it has no evaluation ID.


class UnavailableReasoner:
    """Default provider: no reasoning happens and no evidence leaves the process."""

    async def diagnose(self, evidence_bundle):
        raise DiagnosticError("reasoner_unavailable", "No diagnostic reasoning provider is configured")


def _id(prefix: str, *parts: str) -> str:
    raw = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return prefix + sha256(raw.encode()).hexdigest()[:24]


def _signal_rows(evaluations: list[Evaluation], domain, criterion: str):
    return [(e.internal_id, c) for e in evaluations for c in e.criteria
            if c.domain == domain and c.question.strip() == criterion]


def detect_signals(evaluations: list[Evaluation]) -> list[PerformanceSignal]:
    """One observed signal per criterion, including zero-failure criteria.

    Rank by descending failure count, then failure rate, then domain/criterion.
    No failure threshold or causal label is applied.
    """
    stats = [s for s in analyze(evaluations) if s.question is not None]
    total_evaluations = len(evaluations)
    result = []
    for s in stats:
        rows = _signal_rows(evaluations, s.domain, s.question)
        result.append(PerformanceSignal(
            signal_id=_id("sig_", s.domain.value, s.question), domain=s.domain,
            criterion=s.question, evaluated_results=s.pass_count + s.fail_count,
            evaluated_evaluations=s.evaluations, total_evaluations=total_evaluations,
            pass_count=s.pass_count,
            fail_count=s.fail_count, pass_rate=s.pass_rate, fail_rate=s.fail_rate,
            feedback_count=s.feedback_count, feedback_coverage=s.feedback_coverage,
            max_score_total=s.max_score_total, attained_score_total=s.attained_score_total,
            score_rate=s.score_rate,
            affected_evaluation_ids=sorted({eid for eid, c in rows if not c.passed}),
            source_lineages=s.lineages))
    return sorted(result, key=lambda s: (-s.fail_count, -s.fail_rate, s.domain.value, s.criterion))


def build_bundle(signal: PerformanceSignal, evaluations: list[Evaluation]) -> EvidenceBundle:
    rows = _signal_rows(evaluations, signal.domain, signal.criterion)
    if not rows:
        raise DiagnosticError("ambiguous_evidence", "No criterion records support this signal")
    rows.sort(key=lambda pair: (pair[0], pair[1].lineage.source_filename,
                                 pair[1].lineage.source_sheet, pair[1].lineage.excel_row))
    actual_lineages = Counter((c.lineage.source_filename, c.lineage.source_sheet,
                               c.lineage.excel_row) for _, c in rows)
    stated_lineages = Counter((l.source_filename, l.source_sheet, l.excel_row)
                              for l in signal.source_lineages)
    if (len(rows) != signal.evaluated_results or
            len({eid for eid, _ in rows}) != signal.evaluated_evaluations or
            signal.total_evaluations != len(evaluations) or
            sum(not c.passed for _, c in rows) != signal.fail_count or
            sum(c.passed for _, c in rows) != signal.pass_count or
            sum(bool(c.evaluator_feedback) for _, c in rows) != signal.feedback_count or
            sum((c.max_score for _, c in rows), Decimal(0)) != signal.max_score_total or
            sum((c.attained_score for _, c in rows), Decimal(0)) != signal.attained_score_total or
            actual_lineages != stated_lineages):
        raise DiagnosticError("evidence_mismatch", "Signal and criterion records disagree")
    # Item IDs derive from signal, evaluation, and source location, so a citation is unique
    # across bundles and cannot silently re-point at a different row if the data changes.
    items = [EvidenceItem(item_id=_id("ev_", signal.signal_id, eid, c.lineage.source_filename,
                                      c.lineage.source_sheet, str(c.lineage.excel_row)),
                          evaluation_id=eid, domain=c.domain,
                          criterion=c.question, passed=c.passed, answer=c.answer,
                          max_score=c.max_score, attained_score=c.attained_score,
                          evaluator_feedback=c.evaluator_feedback, source_lineage=c.lineage)
             for eid, c in rows]
    if len({item.item_id for item in items}) != len(items):
        raise DiagnosticError("ambiguous_evidence", "Evidence rows are not distinguishable")
    return EvidenceBundle(signal=signal, items=items)


def validate_references(references: list[EvidenceReference], bundle: EvidenceBundle) -> None:
    valid = {item.item_id: item.evaluation_id for item in bundle.items}
    valid[SIGNAL_REFERENCE] = None
    seen = set()
    for ref in references:
        if ref.item_id not in valid or ref.evaluation_id != valid[ref.item_id]:
            raise DiagnosticError("invalid_evidence_reference", "Evidence citation is outside this bundle")
        key = (ref.item_id, ref.evaluation_id)
        if key in seen:
            raise DiagnosticError("invalid_evidence_reference", "Duplicate evidence citation")
        seen.add(key)


def validate_citations(supporting: list[EvidenceReference], conflicting: list[EvidenceReference],
                       bundle: EvidenceBundle) -> None:
    validate_references(supporting, bundle)
    validate_references(conflicting, bundle)
    support = {(r.item_id, r.evaluation_id) for r in supporting}
    conflict = {(r.item_id, r.evaluation_id) for r in conflicting}
    if support & conflict:
        raise DiagnosticError("invalid_evidence_reference", "Evidence cannot support and conflict simultaneously")


def untrusted_payload(raw: object) -> object:
    """Reduce any boundary input to plain data so validation always runs on fresh objects.

    A pre-built model instance (including one from `model_construct` or a subclass) would
    otherwise pass through `model_validate` unvalidated and stay shared with the caller.
    The reduction is recursive: a mapping whose nested values are model instances or
    mutable containers is copied all the way down, so no provider-owned object survives
    into the validated result. Anything that is not a mapping/model at the top level, or
    that cannot be reduced, becomes `None` and fails validation.
    """
    try:
        return _reduce(raw, depth=0) if isinstance(raw, (BaseModel, Mapping)) else None
    except Exception:
        return None


_MAX_REDUCTION_DEPTH = 32  # Provider output is finite; deeper nesting is refused.


def _reduce(value: object, depth: int) -> object:
    if depth > _MAX_REDUCTION_DEPTH:
        raise ValueError("Boundary payload is nested too deeply")
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python", warnings=False)
    if isinstance(value, Mapping):
        return {str(key): _reduce(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_reduce(item, depth + 1) for item in value]
    return value


_untrusted_payload = untrusted_payload


def validate_provider_output(raw: object, bundle: EvidenceBundle) -> DiagnosticHypothesis:
    payload = _untrusted_payload(raw)
    if payload is None:
        raise ProviderOutputError("invalid_provider_output", "Reasoner returned an invalid hypothesis")
    try:
        hypothesis = DiagnosticHypothesis.model_validate(payload)
    except ValidationError as exc:
        raise ProviderOutputError("invalid_provider_output", "Reasoner returned an invalid hypothesis") from exc
    if hypothesis.provider_metadata.generation_mode is not None:
        # Provenance mode is assigned by the service from the installed object (see
        # `stamp_generation_mode`); a provider or fixture may not assert its own.
        raise ProviderOutputError("invalid_provider_output", "Reasoner may not assert its generation mode")
    if hypothesis.signal_id != bundle.signal.signal_id:
        raise ProviderOutputError("evidence_mismatch", "Reasoner associated a different signal")
    try:
        validate_citations(hypothesis.supporting_evidence, hypothesis.conflicting_evidence, bundle)
    except DiagnosticError as exc:
        raise ProviderOutputError(exc.code, str(exc)) from exc
    return hypothesis


class DiagnosticReasoner(Protocol):
    """Adapter contract. Return a JSON-compatible mapping shaped like `DiagnosticHypothesis`.

    Output is validated by the application regardless of the object type returned.
    """

    async def diagnose(self, evidence_bundle: ProviderEvidenceBundle) -> object: ...


class ControlledTestReasoner:
    """Test double: returns the supplied response verbatim, ignoring the evidence.

    It performs no inference of any kind and must never be installed outside tests.
    """

    controlled_fixture = True  # Reported by /diagnostics/mode; see `provider_kind`.

    def __init__(self, response: object):
        self.response = response

    async def diagnose(self, evidence_bundle: ProviderEvidenceBundle) -> object:
        return self.response


def provider_kind(provider: object) -> str:
    """Classify an installed provider from the object itself, never from a configuration label."""
    if isinstance(provider, UnavailableReasoner):
        return "unavailable"
    if getattr(provider, "controlled_fixture", False) is True:
        return "controlled_fixture"
    return "provider"


# What an installed provider object declares about sending evidence off-process. Values a
# provider may declare about itself; anything else is reported as undeclared, so a provider
# cannot invent a reassuring label through this route.
REMOTE_POLICIES = frozenset({"privacy_blocked", "synthetic_only"})


def remote_invocation_policy(provider: object) -> str:
    """Read from the object, like `provider_kind`. "provider" alone never means "permitted"."""
    if isinstance(provider, UnavailableReasoner):
        return "unavailable"
    if getattr(provider, "controlled_fixture", False) is True:
        return "local_fixture"
    policy = getattr(provider, "remote_invocation_policy", None)
    return policy if policy in REMOTE_POLICIES else "undeclared"


def stamp_generation_mode(hypothesis: DiagnosticHypothesis, provider: object) -> DiagnosticHypothesis:
    """Record how the hypothesis was produced from the installed object, never from its output."""
    mode = "controlled_fixture" if provider_kind(provider) == "controlled_fixture" else "provider"
    metadata = hypothesis.provider_metadata.model_copy(update={"generation_mode": mode})
    return hypothesis.model_copy(update={"provider_metadata": metadata})


# Reasoner-raised errors that may pass to a client, with the only message text allowed for
# each. Any other reasoner exception, including a ProviderOutputError with an unknown code,
# is reported as a generic failure so provider-authored text never reaches a response.
PROVIDER_ERROR_MESSAGES = {
    "provider_privacy_blocked": "Remote diagnosis is disabled for non-synthetic evidence",
    "invalid_provider_input": "Diagnostic evidence is inconsistent",
    "invalid_provider_output": "Reasoner returned an invalid hypothesis",
    "invalid_evidence_reference": "Evidence citation is outside this bundle",
    "reasoner_failure": "Reasoning provider failed",
}


class DiagnosticService:
    """Process-local application service. All state is ephemeral and lost on restart."""

    def __init__(self, evaluations: list[Evaluation], reasoner: DiagnosticReasoner):
        ids = Counter(e.internal_id for e in evaluations)
        if any(count > 1 for count in ids.values()):
            raise DiagnosticError("duplicate_evaluation", "Evaluation records must have unique internal IDs")
        self.evaluations = evaluations
        self.reasoner = reasoner
        self.signals = {s.signal_id: s for s in detect_signals(evaluations)}
        self._records: dict[str, DiagnosticRecord] = {}
        self._bundles: dict[str, EvidenceBundle] = {}
        self._lock = threading.Lock()  # Sync review routes run concurrently in a threadpool.

    def list_signals(self) -> list[PerformanceSignal]:
        return sorted(self.signals.values(), key=lambda s: (-s.fail_count, -s.fail_rate, s.domain.value, s.criterion))

    def list_hypotheses(self, signal_id: str) -> list[DiagnosticRecord]:
        """Return snapshots for one known signal, newest first, without exposing store references."""
        if signal_id not in self.signals:
            raise DiagnosticError("signal_not_found", "Signal was not found")
        with self._lock:
            records = [record.model_copy(deep=True) for record in self._records.values()
                       if record.provider_hypothesis.signal_id == signal_id]
        return list(reversed(records))

    def evidence(self, signal_id: str) -> EvidenceBundle:
        signal = self.signals.get(signal_id)
        if signal is None:
            raise DiagnosticError("signal_not_found", "Signal was not found")
        return build_bundle(signal, self.evaluations)

    def provider_evidence(self, signal_id: str) -> ProviderEvidenceBundle:
        identities = {name for e in self.evaluations for name in
                      (e.agent_name, e.qa_name, e.team_leader)}
        return self.evidence(signal_id).provider_view(identities)

    async def diagnose(self, signal_id: str) -> DiagnosticRecord:
        bundle = self.evidence(signal_id)
        try:
            raw = await self.reasoner.diagnose(self.provider_evidence(signal_id))
        except DiagnosticError as exc:
            if isinstance(self.reasoner, UnavailableReasoner):
                raise
            code = exc.code if isinstance(exc, ProviderOutputError) and exc.code in PROVIDER_ERROR_MESSAGES \
                else "reasoner_failure"
            raise ProviderOutputError(code, PROVIDER_ERROR_MESSAGES[code]) from exc
        except Exception as exc:
            raise ProviderOutputError("reasoner_failure", "Reasoning provider failed") from exc
        hypothesis = stamp_generation_mode(validate_provider_output(raw, bundle), self.reasoner)
        with self._lock:
            if hypothesis.hypothesis_id in self._records:
                raise ProviderOutputError("invalid_provider_output", "Hypothesis ID already exists")
            self._records[hypothesis.hypothesis_id] = DiagnosticRecord(provider_hypothesis=hypothesis)
            self._bundles[hypothesis.hypothesis_id] = bundle
        return self.get(hypothesis.hypothesis_id)

    def _record(self, hypothesis_id: str) -> DiagnosticRecord:
        if hypothesis_id not in self._records:
            raise DiagnosticError("diagnosis_not_found", "Diagnosis was not found")
        return self._records[hypothesis_id]

    def get(self, hypothesis_id: str) -> DiagnosticRecord:
        """Snapshot. Mutating the returned object never changes stored state or audit history."""
        with self._lock:
            return self._record(hypothesis_id).model_copy(deep=True)

    def _event(self, action: str, reviewer_id: str, rationale: str | None = None,
               revision: HumanRevision | None = None) -> ReviewEvent:
        if not reviewer_id.strip():
            raise DiagnosticError("invalid_review", "Reviewer identifier is required")
        return ReviewEvent(action=action, reviewer_id=reviewer_id.strip(),
                           occurred_at=datetime.now(timezone.utc), rationale=rationale,
                           revision=revision)

    def approve(self, hypothesis_id: str, reviewer_id: str) -> DiagnosticRecord:
        with self._lock:
            record = self._record(hypothesis_id)
            if record.status not in ("awaiting_review", "revised") or record.revision_approved:
                raise DiagnosticError("invalid_state_transition", "Diagnosis cannot be approved from this state")
            event = self._event("approve", reviewer_id)
            record.events.append(event)
            if record.status == "revised":
                record.revision_approved = True
            else:
                record.status = "approved"
        return self.get(hypothesis_id)

    def reject(self, hypothesis_id: str, reviewer_id: str, rationale: str) -> DiagnosticRecord:
        with self._lock:
            record = self._record(hypothesis_id)
            if record.status != "awaiting_review":
                raise DiagnosticError("invalid_state_transition", "Diagnosis cannot be rejected from this state")
            if not rationale.strip():
                raise DiagnosticError("invalid_review", "Rejection rationale is required")
            record.events.append(self._event("reject", reviewer_id, rationale))
            record.status = "rejected"
        return self.get(hypothesis_id)

    def revise(self, hypothesis_id: str, reviewer_id: str, revision: object,
               rationale: str) -> DiagnosticRecord:
        with self._lock:
            record = self._record(hypothesis_id)
            if record.status != "awaiting_review":
                raise DiagnosticError("invalid_state_transition", "Diagnosis cannot be revised from this state")
            if not rationale.strip():
                raise DiagnosticError("invalid_review", "Revision rationale is required")
            payload = _untrusted_payload(revision)
            if payload is None:
                raise DiagnosticError("malformed_revision", "Human revision is invalid")
            try:
                validated = HumanRevision.model_validate(payload)
            except ValidationError as exc:
                raise DiagnosticError("malformed_revision", "Human revision is invalid") from exc
            validate_citations(validated.supporting_evidence, validated.conflicting_evidence,
                               self._bundles[hypothesis_id])
            record.events.append(self._event("revise", reviewer_id, rationale, validated))
            record.human_revision = validated
            record.status = "revised"
        return self.get(hypothesis_id)

    def get_approved_diagnosis(self, hypothesis_id: str) -> ApprovedDiagnosis:
        """The only path across the future Design boundary."""
        record = self.get(hypothesis_id)
        if record.status == "approved":
            diagnosis = record.provider_hypothesis
        elif record.status == "revised" and record.revision_approved and record.human_revision:
            diagnosis = record.human_revision
        else:
            raise DiagnosticError("diagnosis_not_approved", "Diagnosis has not been approved")
        approvals = [event for event in record.events if event.action == "approve"]
        if len(approvals) != 1:
            raise DiagnosticError("diagnosis_not_approved", "Approval record is inconsistent")
        decision = approvals[0]
        return ApprovedDiagnosis(hypothesis_id=hypothesis_id,
                                 signal_id=record.provider_hypothesis.signal_id,
                                 diagnosis=diagnosis, approved_by=decision.reviewer_id,
                                 approved_at=decision.occurred_at,
                                 human_revised=record.status == "revised")
