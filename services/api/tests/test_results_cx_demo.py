"""Real-mode wiring tests use generated workbooks only, never supplied QA data."""

import asyncio
from collections import Counter
from decimal import Decimal
from pathlib import Path
import subprocess
import sys

from openpyxl import load_workbook
from fastapi.testclient import TestClient
import pytest

from app.diagnostics.engine import DiagnosticError, DiagnosticService, build_bundle, detect_signals
from app.main import UnavailableReasoner, app
from app.results_cx import PipelineValidationError, normalize
from app.results_cx import demo
from app.results_cx.models import Domain
from test_results_cx import make_workbook


def generated_sources(root: Path):
    for domain, name in demo.REQUIRED_WORKBOOKS.items():
        make_workbook(root, domain.value, filename=name)


def test_real_mode_requires_exact_workbooks_and_never_falls_back(tmp_path):
    with pytest.raises(PipelineValidationError, match="missing_demo_workbooks") as failure:
        demo.load_results_cx_demo(tmp_path / "raw")
    assert all(name in str(failure.value) for name in demo.REQUIRED_WORKBOOKS.values())
    root = tmp_path / "raw"
    generated_sources(root)
    make_workbook(root, "compliance", filename="unrelated.xlsx")
    with pytest.raises(PipelineValidationError, match="unexpected_demo_workbooks"):
        demo.load_results_cx_demo(root)


def test_real_mode_delegates_to_m2_and_keeps_domains_evidence_and_lineage(tmp_path, monkeypatch):
    root = tmp_path / "raw"
    generated_sources(root)
    calls = []
    original = demo.normalize

    def checked_normalize(sources):
        calls.append(set(sources))
        return original(sources)

    monkeypatch.setattr(demo, "normalize", checked_normalize)
    evaluations = demo.load_results_cx_demo(root)
    assert calls == [set(Domain)]
    assert evaluations == normalize(demo.discover_sources(root))
    assert all(e.internal_id.startswith("rcx1_") for e in evaluations)
    signals = detect_signals(evaluations)
    assert len(signals) == 6  # Two generated criteria in each of three domains.
    assert {(s.domain, s.criterion) for s in signals} == {
        (domain, question) for domain in Domain for question in ("Criterion A", "Criterion B")}
    assert [(s.fail_count, s.evaluated_results, s.fail_rate, s.feedback_count)
            for s in signals if s.criterion == "Criterion B"] == [(2, 2, Decimal(1), 2)] * 3
    assert all(s.evaluated_evaluations == 2 for s in signals)
    for signal in signals:
        bundle = build_bundle(signal, evaluations)
        expected = [(e.internal_id, c) for e in evaluations for c in e.criteria
                    if c.domain == signal.domain and c.question.strip() == signal.criterion]
        assert Counter((i.evaluation_id, i.source_lineage.source_filename,
                        i.source_lineage.source_sheet, i.source_lineage.excel_row)
                       for i in bundle.items) == Counter(
            (eid, c.lineage.source_filename, c.lineage.source_sheet, c.lineage.excel_row)
            for eid, c in expected)
        assert all(i.source_lineage.source_filename == demo.REQUIRED_WORKBOOKS[signal.domain]
                   for i in bundle.items)
        assert not {"cause_domain", "performance_dimension", "training_need"} & set(signal.model_dump())


def test_incomplete_criterion_coverage_and_feedback_are_counted_not_assumed(tmp_path):
    root = tmp_path / "raw"
    generated_sources(root)
    path = root / demo.REQUIRED_WORKBOOKS[Domain.COMPLIANCE]
    workbook = load_workbook(path)
    sheet = workbook["Export"]
    sheet.delete_rows(5)  # The second generated evaluation lacks Criterion B in this domain.
    sheet.cell(3, 8).value = None  # First evaluation's Criterion B has no feedback.
    workbook.save(path)
    evaluations = demo.load_results_cx_demo(root)
    signal = next(s for s in detect_signals(evaluations)
                  if s.domain == Domain.COMPLIANCE and s.criterion == "Criterion B")
    assert (signal.evaluated_evaluations, signal.evaluated_results, signal.fail_count,
            signal.fail_rate, signal.feedback_count) == (1, 1, 1, Decimal(1), 0)
    assert len(build_bundle(signal, evaluations).items) == 1


def test_real_mode_has_no_diagnostic_provider(tmp_path):
    root = tmp_path / "raw"
    generated_sources(root)
    service = DiagnosticService(demo.load_results_cx_demo(root), UnavailableReasoner())
    signal = service.list_signals()[0]
    assert service.evidence(signal.signal_id).items
    with pytest.raises(DiagnosticError, match="No diagnostic reasoning provider") as failure:
        asyncio.run(service.diagnose(signal.signal_id))
    assert failure.value.code == "reasoner_unavailable"
    assert service.list_hypotheses(signal.signal_id) == []


def test_operator_mode_endpoint_identifies_real_and_synthetic_modes():
    previous = app.state.demo_mode
    try:
        for mode, provider in (("real_results_cx", "unavailable"),
                               ("synthetic_demo", "controlled_fixture")):
            app.state.demo_mode = mode
            assert TestClient(app).get("/diagnostics/mode").json() == {
                "mode": mode, "diagnostic_provider": provider}
    finally:
        app.state.demo_mode = previous


def test_confidential_paths_are_ignored_and_not_tracked():
    root = Path(__file__).resolve().parents[3]
    paths = [f"data/raw/{name}" for name in demo.REQUIRED_WORKBOOKS.values()]
    paths.append("data/processed/evaluations.jsonl")
    for path in paths:
        assert subprocess.run(["git", "check-ignore", "-q", path], cwd=root).returncode == 0
        assert subprocess.run(["git", "ls-files", "--error-unmatch", path], cwd=root,
                              capture_output=True).returncode != 0


def test_explicit_script_fails_safely_without_workbooks(tmp_path):
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run([sys.executable, "scripts/run_results_cx_demo.py", "--input", str(tmp_path)],
                            cwd=root, capture_output=True, text=True)
    assert result.returncode == 2
    assert "missing_demo_workbooks" in result.stderr
    assert "Mode: REAL RESULTS CX" not in result.stdout
