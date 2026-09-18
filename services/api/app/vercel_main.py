"""Vercel entry point for the public CoachLens synthetic demo.

The public deployment intentionally uses controlled synthetic data only.
No ResultsCX confidential records are loaded.
"""

from app.main import app
from app.diagnostics.engine import DiagnosticService, detect_signals
from app.diagnostics.evidence_validator import EvidenceValidationService
from app.design.demo import DemoDesignFixture
from app.design.service import DesignService
from app.interventions.demo import DemoInterventionFixture, DemoSolutionFixture
from app.interventions.handoff import ValidatedInterventionHandoff
from app.interventions.service import InterventionService
from app.vercel_fixture import (
    DemoFixtureEvidenceValidator,
    DemoFixtureReasoner,
    fixture_evaluations,
)


evaluations = fixture_evaluations()

resolution_signal_id = next(
    signal.signal_id
    for signal in detect_signals(evaluations)
    if signal.criterion == "Resolution summary clarity"
)

app.state.diagnostics = DiagnosticService(
    evaluations,
    DemoFixtureReasoner(resolution_signal_id),
)

app.state.evidence_validations = EvidenceValidationService(
    app.state.diagnostics,
    DemoFixtureEvidenceValidator(),
)

app.state.interventions = InterventionService(
    app.state.diagnostics,
    app.state.evidence_validations,
    DemoInterventionFixture(),
    DemoSolutionFixture(),
)

fixture = DemoDesignFixture(resolution_signal_id)

app.state.designs = DesignService(
    app.state.diagnostics,
    ValidatedInterventionHandoff(app.state.interventions),
    fixture,
    controlled_fixture=True,
)

app.state.demo_mode = "synthetic_demo"
