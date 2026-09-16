"""Deterministic evidence, untrusted provider boundary, and human review."""

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from typing import Protocol

from pydantic import ValidationError

from app.results_cx.models import Evaluation
from app.results_cx.pipeline import analyze

from .models import (ApprovedDiagnosis, DiagnosticHypothesis, DiagnosticRecord,
                     EvidenceBundle, EvidenceItem, EvidenceReference, HumanRevision,
                     PerformanceSignal, ProviderEvidenceBundle, ReviewEvent)


class DiagnosticError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _id(prefix: str, *parts: str) -> str:
    raw = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return prefix + sha256(raw.encode()).hexdigest()[:24]


def detect_signals(evaluations: list[Evaluation]) -> list[PerformanceSignal]:
    """One observed signal per criterion, including zero-failure criteria.

    Rank by descending failure count, then failure rate, then domain/criterion.
    No failure threshold or causal label is applied.
    """
    stats = [s for s in analyze(evaluations) if s.question is not None]
    result = []
    for s in stats:
        rows = [(e.internal_id, c) for e in evaluations for c in e.criteria
                if c.domain == s.domain and c.question.strip() == s.question]
        result.append(PerformanceSignal(
            signal_id=_id("sig_", s.domain.value, s.question), domain=s.domain,
            criterion=s.question, evaluated_results=s.pass_count + s.fail_count,
            evaluated_evaluations=s.evaluations, pass_count=s.pass_count,
            fail_count=s.fail_count, pass_rate=s.pass_rate, fail_rate=s.fail_rate,
            feedback_count=s.feedback_count, feedback_coverage=s.feedback_coverage,
            max_score_total=s.max_score_total, attained_score_total=s.attained_score_total,
            score_rate=s.score_rate,
            affected_evaluation_ids=sorted({eid for eid, c in rows if not c.passed}),
            source_lineages=s.lineages))
    return sorted(result, key=lambda s: (-s.fail_count, -s.fail_rate, s.domain.value, s.criterion))


def build_bundle(signal: PerformanceSignal, evaluations: list[Evaluation]) -> EvidenceBundle:
    rows = [(e.internal_id, c) for e in evaluations for c in e.criteria
            if c.domain == signal.domain and c.question.strip() == signal.criterion]
    if not rows:
        raise DiagnosticError("ambiguous_evidence", "No criterion records support this signal")
    rows.sort(key=lambda pair: (pair[0], pair[1].lineage.source_filename,
                                 pair[1].lineage.source_sheet, pair[1].lineage.excel_row))
    actual_lineages = Counter((c.lineage.source_filename, c.lineage.source_sheet,
                               c.lineage.excel_row) for _, c in rows)
    stated_lineages = Counter((l.source_filename, l.source_sheet, l.excel_row)
                              for l in signal.source_lineages)
    if (len(rows) != signal.evaluated_results or
            sum(not c.passed for _, c in rows) != signal.fail_count or
            sum(c.passed for _, c in rows) != signal.pass_count or
            sum(bool(c.evaluator_feedback) for _, c in rows) != signal.feedback_count or
            sum((c.max_score for _, c in rows), Decimal(0)) != signal.max_score_total or
            sum((c.attained_score for _, c in rows), Decimal(0)) != signal.attained_score_total or
            actual_lineages != stated_lineages):
        raise DiagnosticError("evidence_mismatch", "Signal and criterion records disagree")
    items = [EvidenceItem(item_id=f"row_{n}", evaluation_id=eid, domain=c.domain,
                          criterion=c.question, passed=c.passed, answer=c.answer,
                          max_score=c.max_score, attained_score=c.attained_score,
                          evaluator_feedback=c.evaluator_feedback, source_lineage=c.lineage)
             for n, (eid, c) in enumerate(rows, 1)]
    return EvidenceBundle(signal=signal, items=items)


def validate_references(references: list[EvidenceReference], bundle: EvidenceBundle) -> None:
    valid = {item.item_id: item.evaluation_id for item in bundle.items}
    valid["signal"] = None  # Aggregate reference; no evaluation ID is possible.
    seen = set()
    for ref in references:
        if ref.item_id not in valid or ref.evaluation_id != valid[ref.item_id]:
            raise DiagnosticError("invalid_evidence_reference", "Evidence citation is outside this bundle")
        key = (ref.item_id, ref.evaluation_id)
        if key in seen:
            raise DiagnosticError("invalid_evidence_reference", "Duplicate evidence citation")
        seen.add(key)


def validate_provider_output(raw: object, bundle: EvidenceBundle) -> DiagnosticHypothesis:
    try:
        hypothesis = DiagnosticHypothesis.model_validate(raw)
    except ValidationError as exc:
        raise DiagnosticError("invalid_provider_output", "Reasoner returned an invalid hypothesis") from exc
    if hypothesis.signal_id != bundle.signal.signal_id:
        raise DiagnosticError("evidence_mismatch", "Reasoner associated a different signal")
    validate_references(hypothesis.supporting_evidence, bundle)
    validate_references(hypothesis.conflicting_evidence, bundle)
    support = {(r.item_id, r.evaluation_id) for r in hypothesis.supporting_evidence}
    conflict = {(r.item_id, r.evaluation_id) for r in hypothesis.conflicting_evidence}
    if support & conflict:
        raise DiagnosticError("invalid_evidence_reference", "Evidence cannot support and conflict simultaneously")
    return hypothesis


class DiagnosticReasoner(Protocol):
    async def diagnose(self, evidence_bundle: ProviderEvidenceBundle) -> object: ...


class ControlledTestReasoner:
    """Returns a supplied response verbatim. It performs no causal inference."""

    def __init__(self, response: object):
        self.response = response

    async def diagnose(self, evidence_bundle: ProviderEvidenceBundle) -> object:
        return self.response


class DiagnosticService:
    def __init__(self, evaluations: list[Evaluation], reasoner: DiagnosticReasoner):
        self.evaluations = evaluations
        self.reasoner = reasoner
        self.signals = {s.signal_id: s for s in detect_signals(evaluations)}
        self.records: dict[str, DiagnosticRecord] = {}  # Ephemeral, process-local.
        self.bundles: dict[str, EvidenceBundle] = {}

    def list_signals(self) -> list[PerformanceSignal]:
        return sorted(self.signals.values(), key=lambda s: (-s.fail_count, -s.fail_rate, s.domain.value, s.criterion))

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
        except DiagnosticError:
            raise
        except Exception as exc:
            raise DiagnosticError("reasoner_failure", "Reasoning provider failed") from exc
        hypothesis = validate_provider_output(raw, bundle)
        if hypothesis.hypothesis_id in self.records:
            raise DiagnosticError("invalid_provider_output", "Hypothesis ID already exists")
        record = DiagnosticRecord(provider_hypothesis=hypothesis)
        self.records[hypothesis.hypothesis_id] = record
        self.bundles[hypothesis.hypothesis_id] = bundle
        return record

    def get(self, hypothesis_id: str) -> DiagnosticRecord:
        if hypothesis_id not in self.records:
            raise DiagnosticError("diagnosis_not_found", "Diagnosis was not found")
        return self.records[hypothesis_id]

    def _event(self, action: str, reviewer_id: str, rationale: str | None = None,
               revision: HumanRevision | None = None) -> ReviewEvent:
        if not reviewer_id.strip():
            raise DiagnosticError("invalid_review", "Reviewer identifier is required")
        return ReviewEvent(action=action, reviewer_id=reviewer_id.strip(),
                           occurred_at=datetime.now(timezone.utc), rationale=rationale,
                           revision=revision)

    def approve(self, hypothesis_id: str, reviewer_id: str) -> DiagnosticRecord:
        record = self.get(hypothesis_id)
        if record.status not in ("awaiting_review", "revised") or record.revision_approved:
            raise DiagnosticError("invalid_state_transition", "Diagnosis cannot be approved from this state")
        record.events.append(self._event("approve", reviewer_id))
        if record.status == "revised":
            record.revision_approved = True
        else:
            record.status = "approved"
        return record

    def reject(self, hypothesis_id: str, reviewer_id: str, rationale: str) -> DiagnosticRecord:
        record = self.get(hypothesis_id)
        if record.status != "awaiting_review":
            raise DiagnosticError("invalid_state_transition", "Diagnosis cannot be rejected from this state")
        if not rationale.strip():
            raise DiagnosticError("invalid_review", "Rejection rationale is required")
        record.events.append(self._event("reject", reviewer_id, rationale))
        record.status = "rejected"
        return record

    def revise(self, hypothesis_id: str, reviewer_id: str, revision: HumanRevision,
               rationale: str) -> DiagnosticRecord:
        record = self.get(hypothesis_id)
        if record.status != "awaiting_review":
            raise DiagnosticError("invalid_state_transition", "Diagnosis cannot be revised from this state")
        if not rationale.strip():
            raise DiagnosticError("invalid_review", "Revision rationale is required")
        try:
            revision = HumanRevision.model_validate(revision)
        except ValidationError as exc:
            raise DiagnosticError("malformed_revision", "Human revision is invalid") from exc
        bundle = self.bundles[hypothesis_id]
        validate_references(revision.supporting_evidence, bundle)
        validate_references(revision.conflicting_evidence, bundle)
        if set((r.item_id, r.evaluation_id) for r in revision.supporting_evidence) & set(
                (r.item_id, r.evaluation_id) for r in revision.conflicting_evidence):
            raise DiagnosticError("invalid_evidence_reference", "Evidence cannot support and conflict simultaneously")
        record.events.append(self._event("revise", reviewer_id, rationale, revision))
        record.human_revision = revision
        record.status = "revised"
        return record

    def get_approved_diagnosis(self, hypothesis_id: str) -> ApprovedDiagnosis:
        record = self.get(hypothesis_id)
        if record.status == "approved":
            decision = record.events[-1]
            diagnosis = record.provider_hypothesis
        elif record.status == "revised" and record.revision_approved and record.human_revision:
            decision = record.events[-1]
            diagnosis = record.human_revision
        else:
            raise DiagnosticError("diagnosis_not_approved", "Diagnosis has not been approved")
        return ApprovedDiagnosis(hypothesis_id=hypothesis_id,
                                 signal_id=record.provider_hypothesis.signal_id,
                                 diagnosis=diagnosis, approved_by=decision.reviewer_id,
                                 approved_at=decision.occurred_at,
                                 human_revised=record.status == "revised")
