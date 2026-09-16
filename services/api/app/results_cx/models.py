"""Canonical records. Raw identity and comments are local-only sensitive data."""

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class Domain(StrEnum):
    BUSINESS_PROCESS = "business_process"
    COMPLIANCE = "compliance"
    MEMBER_EXPERIENCE = "member_experience"


class SourceLineage(BaseModel):
    source_filename: str
    source_sheet: str
    excel_row: int = Field(ge=2)


class CriterionResult(BaseModel):
    domain: Domain
    question: str
    answer: str
    passed: bool
    max_score: Decimal = Field(ge=0)
    attained_score: Decimal = Field(ge=0)
    evaluator_feedback: str | None
    lineage: SourceLineage


class Evaluation(BaseModel):
    internal_id: str
    agent_name: str
    call_date: date
    qa_name: str
    team_leader: str
    evaluation_date: date | None = None
    criteria: list[CriterionResult]


class Statistic(BaseModel):
    domain: Domain
    question: str | None = None
    evaluations: int
    pass_count: int
    fail_count: int
    pass_rate: Decimal
    fail_rate: Decimal
    feedback_count: int
    feedback_coverage: Decimal
    max_score_total: Decimal
    attained_score_total: Decimal
    score_rate: Decimal
    lineages: list[SourceLineage] = Field(exclude=True)
