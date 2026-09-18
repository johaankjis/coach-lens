"""Invoke the AWS-5 Bedrock Training Designer once with synthetic input only.

Uses the normal AWS credential provider chain. No ResultsCX record, comment, name, or
lineage is loaded: the diagnosis and intervention are fixed synthetic fixtures, so the only
remote content is fixture text plus the versioned design guidance.
"""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import get_settings  # noqa: E402
from app.design.bedrock import BedrockTrainingDesigner  # noqa: E402
from app.design.demo import DemoDesignFixture  # noqa: E402
from app.design.service import DesignError, DesignService  # noqa: E402
from app.diagnostics.engine import DiagnosticService  # noqa: E402
from run_m4_demo import DemoFixtureReasoner, fixture_evaluations  # noqa: E402


async def main():
    settings = get_settings()
    if settings.diagnostic_evaluations_path is not None:
        raise SystemExit("Training smoke refuses a configured local evaluations path")
    if not settings.bedrock_enabled:
        raise SystemExit("Set COACHLENS_BEDROCK_ENABLED=true for the training smoke")
    evaluations = fixture_evaluations()
    diagnostics = DiagnosticService(evaluations, DemoFixtureReasoner("unused"))
    signal = next(s for s in diagnostics.list_signals() if s.criterion == "Resolution summary clarity")
    diagnostics.reasoner = DemoFixtureReasoner(signal.signal_id)
    record = await diagnostics.diagnose(signal.signal_id)
    diagnostics.approve(record.provider_hypothesis.hypothesis_id, "smoke-reviewer")
    response_diagnostics = []
    designer = BedrockTrainingDesigner(settings.bedrock_region, settings.bedrock_model_id,
                                       diagnostics=diagnostics, diagnostic_sink=response_diagnostics.append)
    designs = DesignService(diagnostics, DemoDesignFixture(signal.signal_id), designer)
    try:
        result = await designs.run(record.provider_hypothesis.hypothesis_id)
    except DesignError as exc:
        if response_diagnostics:
            print({"designer_response_diagnostic": response_diagnostics[-1]})
        print({"error_code": exc.code, "message": str(exc)})
        raise SystemExit(1)
    design = result.training_design
    print({"status": result.status, "generation_mode": result.generation_mode,
           "provider": design.provider_metadata.provider, "model": design.provider_metadata.model,
           "invocation_region": design.provider_metadata.invocation_region,
           "training_focus": design.design_basis.intervention.training_focus.value,
           "guidance_version": design.design_basis.guidance_version,
           "target_behaviors": len(design.target_behaviors), "objectives": len(design.objectives),
           "sections": len(design.outline), "activities": len(design.activities),
           "knowledge_checks": len(design.decision_checks),
           "practice_scenarios": len(design.practice_scenarios),
           "practice_turns": sum(len(s.beats) for s in design.practice_scenarios),
           "rubric_criteria": sum(len(s.rubric) for s in design.practice_scenarios),
           "missing_operational_details": len(design.missing_operational_details),
           "alignment_links": len(result.alignment_trace.links)})


if __name__ == "__main__":
    asyncio.run(main())
