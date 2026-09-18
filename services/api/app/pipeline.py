"""One object graph for everything downstream of the diagnostic service.

`app.main` and the real ResultsCX demo installer both build the same chain from whichever
diagnostic service they installed:

    diagnostics -> evidence validator (AWS-3) -> intervention service (AWS-4)
                -> design service (M5) whose intervention step is the AWS-4 handoff and whose
                   training designer is the AWS-5 Bedrock designer behind the Bedrock flag

Building it in one place keeps the services bound to the same active diagnostic service,
never to a stale import-time instance, and keeps the two startup paths from drifting apart.
"""

from dataclasses import dataclass

from app.config import Settings
from app.design.bedrock import BedrockTrainingDesigner
from app.design.service import DesignService, UnavailableDesignProvider
from app.diagnostics.engine import DiagnosticService
from app.diagnostics.evidence_validator import (BedrockEvidenceValidator, EvidenceValidationService,
                                                 UnavailableEvidenceValidator)
from app.interventions.bedrock import BedrockInterventionReasoner, BedrockSolutionValidator
from app.interventions.handoff import ValidatedInterventionHandoff
from app.interventions.service import (InterventionService, UnavailableInterventionReasoner,
                                       UnavailableSolutionValidator)


@dataclass(frozen=True)
class Pipeline:
    diagnostics: DiagnosticService
    evidence_validations: EvidenceValidationService
    interventions: InterventionService
    designs: DesignService


def build_pipeline(diagnostics: DiagnosticService, settings: Settings) -> Pipeline:
    """Every remote adapter follows the one Bedrock switch; nothing here is a fixture.

    The AWS-4 handoff is the only intervention source for the design service, so a training
    package can only be generated for an intervention whose solution review found it aligned.
    Each Bedrock adapter still applies its own privacy gate at invocation time.
    """
    region, model = settings.bedrock_region, settings.bedrock_model_id
    remote = settings.bedrock_enabled
    evidence_validations = EvidenceValidationService(
        diagnostics,
        BedrockEvidenceValidator(region, model) if remote else UnavailableEvidenceValidator())
    interventions = InterventionService(
        diagnostics, evidence_validations,
        BedrockInterventionReasoner(region, model) if remote else UnavailableInterventionReasoner(),
        BedrockSolutionValidator(region, model) if remote else UnavailableSolutionValidator())
    designs = DesignService(
        diagnostics, ValidatedInterventionHandoff(interventions),
        BedrockTrainingDesigner(region, model, diagnostics=diagnostics) if remote else UnavailableDesignProvider())
    return Pipeline(diagnostics=diagnostics, evidence_validations=evidence_validations,
                    interventions=interventions, designs=designs)


def install_pipeline(app, diagnostics: DiagnosticService, settings: Settings) -> Pipeline:
    """Replace every downstream service on `app.state` together, bound to `diagnostics`."""
    pipeline = build_pipeline(diagnostics, settings)
    app.state.diagnostics = pipeline.diagnostics
    app.state.evidence_validations = pipeline.evidence_validations
    app.state.interventions = pipeline.interventions
    app.state.designs = pipeline.designs
    return pipeline
