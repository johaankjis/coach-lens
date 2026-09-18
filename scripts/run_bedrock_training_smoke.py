"""Exercise the integrated AWS-4 -> AWS-5 application contract with synthetic input only.

    synthetic QA rows -> fixed diagnosis fixture -> synthetic human approval
      -> AWS-4 Intervention Reasoner (fixed fixture) -> AWS-4 Solution Validator (fixed fixture)
      -> AWS-4 DesignHandoff -> AWS-5 Bedrock Training Designer (the one live call)

The upstream stages are the M4 demo's fixed, non-AI fixtures so the story is deterministic;
the design step is the real `DesignService` with the real `ValidatedInterventionHandoff`, so
the designer is only ever invoked the way the application invokes it. All three synthetic
signals run:

    resolution clarity      skill gap    -> practice_simulation -> aligned -> package generated
    workflow prompt missing process gap  -> process_correction  -> aligned -> no package, no call
    follow-up documented    undetermined -> investigate_further -> aligned -> no package, no call

Uses the normal AWS credential provider chain. No ResultsCX record, comment, name, or lineage
is loaded. Prints counts, enums, and identifiers only. `main(client=...)` accepts a stub
Converse client so the automated suite can drive the same harness without AWS.
"""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import get_settings  # noqa: E402
from app.design.bedrock import BedrockTrainingDesigner  # noqa: E402
from app.design.service import DesignError, DesignService  # noqa: E402
from app.diagnostics.engine import DiagnosticService, detect_signals  # noqa: E402
from app.interventions.demo import DemoInterventionFixture, DemoSolutionFixture  # noqa: E402
from app.interventions.handoff import ValidatedInterventionHandoff  # noqa: E402
from app.interventions.service import InterventionService  # noqa: E402
from run_m4_demo import DemoFixtureReasoner, fixture_evaluations  # noqa: E402


RESOLUTION_CRITERION = "Resolution summary clarity"


def build_pipeline(settings, *, client=None, diagnostic_sink=None):
    """The application object graph with fixture upstream stages and a live designer."""
    evaluations = fixture_evaluations()
    resolution = next(s.signal_id for s in detect_signals(evaluations) if s.criterion == RESOLUTION_CRITERION)
    diagnostics = DiagnosticService(evaluations, DemoFixtureReasoner(resolution))
    interventions = InterventionService(diagnostics, None, DemoInterventionFixture(), DemoSolutionFixture())
    designer = BedrockTrainingDesigner(settings.bedrock_region, settings.bedrock_model_id, client=client,
                                       diagnostics=diagnostics, diagnostic_sink=diagnostic_sink)
    designs = DesignService(diagnostics, ValidatedInterventionHandoff(interventions), designer)
    return diagnostics, interventions, designs


def summarize(record, result):
    """Counts, enums, and identifiers only: no generated text."""
    summary = {"intervention_type": record.proposal.intervention_type.value,
               "alignment_outcome": record.solution_validation.alignment_outcome.value,
               "solution_status": record.status,
               "training_design_gate": record.handoff.training_design_gate,
               "design_status": result.status, "generation_mode": result.generation_mode,
               "training_package": result.training_design is not None}
    if result.training_design is None:
        return summary
    design = result.training_design
    basis = design.design_basis
    return summary | {
        "provider": design.provider_metadata.provider, "model": design.provider_metadata.model,
        "invocation_region": design.provider_metadata.invocation_region,
        "validation_source": basis.intervention.validation_source,
        "intervention_id_matches": basis.intervention.intervention_id == record.proposal.intervention_id,
        "solution_validation_id_matches": (basis.intervention.solution_validation_id
                                           == record.solution_validation.solution_validation_id),
        "training_focus": basis.intervention.training_focus.value,
        "guidance_version": basis.guidance_version,
        "target_behaviors": len(design.target_behaviors), "objectives": len(design.objectives),
        "sections": len(design.outline), "activities": len(design.activities),
        "knowledge_checks": len(design.decision_checks),
        "practice_scenarios": len(design.practice_scenarios),
        "practice_turns": sum(len(s.beats) for s in design.practice_scenarios),
        "rubric_criteria": sum(len(s.rubric) for s in design.practice_scenarios),
        "missing_operational_details": len(design.missing_operational_details),
        "alignment_links": len(result.alignment_trace.links)}


async def main(client=None):
    settings = get_settings()
    if settings.diagnostic_evaluations_path is not None:
        raise SystemExit("Training smoke refuses a configured local evaluations path")
    if not settings.bedrock_enabled:
        raise SystemExit("Set COACHLENS_BEDROCK_ENABLED=true for the training smoke")
    response_diagnostics = []
    diagnostics, interventions, designs = build_pipeline(settings, client=client,
                                                         diagnostic_sink=response_diagnostics.append)
    outcomes = {}
    for signal in diagnostics.list_signals():
        record = await diagnostics.diagnose(signal.signal_id)
        hypothesis_id = record.provider_hypothesis.hypothesis_id
        diagnostics.approve(hypothesis_id, "smoke-reviewer")
        await interventions.propose(hypothesis_id)
        intervention = await interventions.validate_solution(hypothesis_id)
        try:
            result = await designs.run(hypothesis_id)
        except DesignError as exc:
            if response_diagnostics:
                print({"designer_response_diagnostic": response_diagnostics[-1]})
            print({"criterion": signal.criterion, "error_code": exc.code, "message": str(exc)})
            raise SystemExit(1)
        outcomes[signal.criterion] = summarize(intervention, result)
        print({"criterion": signal.criterion, **outcomes[signal.criterion]})
    return outcomes


if __name__ == "__main__":
    asyncio.run(main())
