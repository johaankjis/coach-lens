"""Synthetic workbook tests: no ResultsCX names, comments, or identifiers."""

from datetime import datetime
import json
from pathlib import Path

from openpyxl import Workbook, load_workbook
import pytest

from app.results_cx import (PipelineValidationError, analyze, discover_sources,
                            normalize, profile_sources, write_jsonl)
from app.results_cx.models import Domain, Evaluation
from app.results_cx.pipeline import evaluation_id


COMMON = ["QA Name", "Team Leader", "AgentNames", "Date of Call", "Questions",
          "Answers", "Feedback answers", "MaxScore", "Score"]
MARKERS = {"business_process": "Business Pass Count", "compliance": "Compliance Pass Count",
           "member_experience": "QA Pass Count"}


def make_workbook(root: Path, domain: str, *, rows=None, filename=None, headers=None):
    root.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Export"
    columns = headers or (COMMON[:4] + (["Date of Evaluation"] if domain == "compliance" else []) + COMMON[4:] + [MARKERS[domain]])
    sheet.append(columns)
    if rows is None:
        rows = [
            {"QA Name": "Evaluator A", "Team Leader": "Lead A", "AgentNames": agent,
             "Date of Call": datetime(2026, 1, day), "Date of Evaluation": datetime(2026, 1, day + 1),
             "Questions": question, "Answers": answer, "Feedback answers": feedback,
             "MaxScore": 10, "Score": 10 if answer.casefold() == "yes" else 0,
             MARKERS[domain]: 1 if answer.casefold() == "yes" else 0}
            for agent, day in (("Agent A", 1), ("Agent B", 2))
            for question, answer, feedback in (("Criterion A", "yes", None), ("Criterion B", "No", "Synthetic note"))
        ]
    for row in rows:
        sheet.append([row.get(column) for column in columns])
    sheet.append(["Total" if column == "QA Name" else None for column in columns])
    path = root / (filename or f"renamed-{domain}.xlsx")
    workbook.save(path)
    return path


@pytest.fixture
def sources(tmp_path):
    root = tmp_path / "raw"
    for domain in MARKERS:
        make_workbook(root, domain)
    return discover_sources(root)


def test_schema_discovery_and_profile(sources):
    assert set(sources) == set(Domain)
    assert all(source.sheet == "Export" for source in sources.values())
    profiles = profile_sources(sources)
    assert len(profiles) == 3
    assert all(profile["criterion_row_count"] == 4 for profile in profiles)
    assert all(profile["distinct_evaluated_calls"] == 2 for profile in profiles)
    assert all(profile["agent_count"] == 2 for profile in profiles)
    assert all(profile["answer_distribution"] == {"Yes": 2, "No": 2} for profile in profiles)
    assert all("Agent A" not in json.dumps(profile) and "Synthetic note" not in json.dumps(profile) for profile in profiles)


def test_discovery_uses_schema_not_sheet_or_filename(tmp_path):
    root = tmp_path / "raw"
    paths = [make_workbook(root, domain, filename=f"source-{index}.xlsx")
             for index, domain in enumerate(MARKERS)]
    workbook = load_workbook(paths[0])
    workbook["Export"].title = "QA Rows"
    workbook.save(paths[0])
    found = discover_sources(root)
    assert found[Domain.BUSINESS_PROCESS].sheet == "QA Rows"


def test_original_answer_and_question_are_preserved(sources):
    source = sources[Domain.BUSINESS_PROCESS]
    workbook = load_workbook(source.path)
    sheet = workbook["Export"]
    sheet.cell(2, 5).value = " Criterion A "
    sheet.cell(2, 6).value = " Yes "
    workbook.save(source.path)
    result = normalize(sources)[0].criteria[0]
    assert result.question == " Criterion A "
    assert result.answer == " Yes "
    assert result.passed is True


def test_missing_and_duplicate_domains(tmp_path):
    root = tmp_path / "raw"
    make_workbook(root, "business_process")
    with pytest.raises(PipelineValidationError, match="missing_domain"):
        discover_sources(root)
    make_workbook(root, "compliance")
    make_workbook(root, "member_experience")
    make_workbook(root, "compliance", filename="another-compliance.xlsx")
    with pytest.raises(PipelineValidationError, match="duplicate_domain"):
        discover_sources(root)


def test_rejects_unsupported_and_ambiguous_schema(tmp_path):
    root = tmp_path / "raw"
    for domain in MARKERS:
        make_workbook(root, domain)
    make_workbook(root, "business_process", filename="bad.xlsx", headers=["Wrong", MARKERS["business_process"]])
    with pytest.raises(PipelineValidationError, match="missing_columns"):
        discover_sources(root)
    (root / "bad.xlsx").unlink()
    make_workbook(root, "business_process", filename="bad.xlsx", headers=COMMON + list(MARKERS.values()))
    with pytest.raises(PipelineValidationError, match="ambiguous_domain"):
        discover_sources(root)


def test_normalization_join_id_and_lineage(sources):
    evaluations = normalize(sources)
    assert len(evaluations) == 2
    assert all(isinstance(e, Evaluation) and len(e.criteria) == 6 for e in evaluations)
    assert all({c.domain for c in e.criteria} == set(Domain) for e in evaluations)
    first = evaluations[0]
    assert first.internal_id == evaluation_id((first.agent_name, first.call_date, first.qa_name, first.team_leader))
    assert first.internal_id == normalize(sources)[0].internal_id
    assert first.evaluation_date.isoformat() == "2026-01-02"
    assert {c.lineage.source_sheet for c in first.criteria} == {"Export"}
    assert {c.lineage.excel_row for c in first.criteria} == {2, 3}
    assert {c.lineage.source_filename for c in first.criteria} == {s.path.name for s in sources.values()}
    assert all(c.passed == (c.answer.casefold() == "yes") for c in first.criteria)


def test_analytics_and_output_is_local_only(sources, tmp_path):
    evaluations = normalize(sources)
    stats = analyze(evaluations)
    domain_stats = [s for s in stats if s.question is None]
    assert len(domain_stats) == 3
    for stat in domain_stats:
        assert (stat.evaluations, stat.pass_count, stat.fail_count, stat.feedback_count) == (2, 2, 2, 2)
        assert (stat.pass_rate, stat.fail_rate, stat.feedback_coverage) == (0.5, 0.5, 0.5)
        assert (stat.max_score_total, stat.attained_score_total, stat.score_rate) == (40, 20, 0.5)
        assert len(stat.lineages) == 4
        assert "lineages" not in stat.model_dump()
    criterion = next(s for s in stats if s.domain == Domain.COMPLIANCE and s.question == "Criterion A")
    assert (criterion.evaluations, criterion.pass_count, criterion.fail_count, criterion.feedback_count) == (2, 2, 0, 0)
    target = write_jsonl(evaluations, tmp_path / "data" / "processed")
    loaded = [Evaluation.model_validate_json(line) for line in target.read_text().splitlines()]
    assert [e.internal_id for e in loaded] == [e.internal_id for e in evaluations]
    with pytest.raises(PipelineValidationError, match="unsafe_output"):
        write_jsonl(evaluations, tmp_path / "export")


def test_duplicate_candidate_key_fails(sources):
    source = sources[Domain.COMPLIANCE]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Export"
    rows = list(load_workbook(source.path, data_only=True)["Export"].values)
    for row in rows:
        sheet.append(row)
    sheet.append(rows[1])
    workbook.save(source.path)
    with pytest.raises(PipelineValidationError, match="duplicate_candidate_key"):
        normalize(sources)


def test_missing_counterpart_and_metadata_mismatch(sources):
    source = sources[Domain.MEMBER_EXPERIENCE]
    workbook = load_workbook(source.path)
    sheet = workbook["Export"]
    sheet.delete_rows(2, 2)
    workbook.save(source.path)
    with pytest.raises(PipelineValidationError, match="missing_counterpart"):
        normalize(sources)
    # Restore the fixture and change a join metadata field in both criterion rows.
    make_workbook(source.path.parent, "member_experience")
    workbook = load_workbook(source.path)
    sheet = workbook["Export"]
    for row in (2, 3):
        sheet.cell(row, 1).value = "Evaluator B"
    workbook.save(source.path)
    with pytest.raises(PipelineValidationError, match="share agent/date with different evaluator"):
        normalize(sources)


def test_invalid_answer_and_conflicting_evaluation_date(sources):
    source = sources[Domain.BUSINESS_PROCESS]
    workbook = load_workbook(source.path)
    workbook["Export"].cell(2, 6).value = "Maybe"
    workbook.save(source.path)
    with pytest.raises(PipelineValidationError, match="invalid_answer"):
        normalize(sources)
    make_workbook(source.path.parent, "business_process")
    source = sources[Domain.COMPLIANCE]
    workbook = load_workbook(source.path)
    workbook["Export"].cell(3, 5).value = datetime(2026, 1, 10)
    workbook.save(source.path)
    with pytest.raises(PipelineValidationError, match="inconsistent_metadata"):
        normalize(sources)
