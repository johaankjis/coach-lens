"""The AWS-4 -> M5/AWS-5 handoff.

`ValidatedInterventionHandoff` implements the M5 `InterventionReasoner` protocol, so the
existing `DesignService` orchestration and `validate_decision` checks are unchanged. Instead
of asking a provider to decide, it reads the stored AWS-4 record and projects it onto the M5
`InterventionDecision` contract. The training designer therefore only ever runs on a
training or practice intervention whose solution review did not question it; coaching,
process correction, and investigation are recorded as non-training or investigate results
and never reach the training generator.
"""

from app.design.models import DesignInput
from app.design.service import DesignError

from .bedrock import InterventionError
from .models import InterventionRecord
from .service import InterventionService, intervention_provider_kind


# Fixed messages for the only handoff conditions that may reach a client through M5.
HANDOFF_ERRORS = {
    "intervention_not_proposed": "Propose and validate an intervention before design",
    "solution_not_validated": "Validate the proposed intervention before design",
    "training_design_withheld": "Training design withheld: the solution review questioned the proposed training",
    "intervention_stale": "The stored intervention does not match the current validated diagnosis",
}


def decision_from_record(record: InterventionRecord, context: DesignInput) -> dict:
    """Project an AWS-4 record onto the M5 InterventionDecision shape. No content is invented:
    next actions are the reasoner's recommendation and target change, verbatim."""
    proposal = record.proposal
    validation = record.solution_validation
    unresolved = list(proposal.missing_evidence)
    if validation is not None:
        unresolved.extend(gap for gap in validation.missing_information if gap not in unresolved)
    run = context.run_id
    return {
        "run_id": run, "diagnosis_id": context.approved.hypothesis_id,
        "decision_type": record.handoff.decision_type.value,
        "intervention_type": proposal.intervention_type.value,
        "target_change": proposal.target_change,
        "solution_alignment": validation.alignment_outcome.value if validation else None,
        "intervention_id": proposal.intervention_id,
        "solution_validation_id": validation.solution_validation_id if validation else None,
        "rationale": proposal.rationale,
        "evidence_refs": [ref.model_dump() for ref in proposal.evidence_refs],
        "risks": list(proposal.limitations),
        "unresolved_questions": unresolved,
        "next_actions": [{"action_id": run + "/N1", "title": "Proposed intervention",
                          "instructions": proposal.recommendation},
                         {"action_id": run + "/N2", "title": "Target behavior or operational change",
                          "instructions": proposal.target_change}],
        # M5 stamps `DesignResult.generation_mode` itself and refuses metadata that asserts one.
        "provider_metadata": proposal.provider_metadata.model_dump(exclude={"generation_mode"}),
    }


class ValidatedInterventionHandoff:
    """M5 intervention step backed by the AWS-4 record instead of a fresh provider decision."""

    def __init__(self, interventions: InterventionService):
        self.interventions = interventions

    def upstream_provider_kind(self) -> str:
        """Reported through `design_provider_kind` from the installed reasoner object."""
        return intervention_provider_kind(self.interventions.reasoner)

    async def decide(self, context: DesignInput) -> dict:
        hypothesis_id = context.approved.hypothesis_id
        try:
            record = self.interventions.get(hypothesis_id)
        except InterventionError as exc:
            code = "intervention_not_proposed" if exc.code == "intervention_not_found" else "intervention_stale"
            raise DesignError(code, HANDOFF_ERRORS[code]) from exc
        if record.validated_diagnosis.approved_at != context.approved.approved_at:
            raise DesignError("intervention_stale", HANDOFF_ERRORS["intervention_stale"])
        if record.solution_validation is None:
            raise DesignError("solution_not_validated", HANDOFF_ERRORS["solution_not_validated"])
        if record.handoff.training_design_gate == "withheld":
            raise DesignError("training_design_withheld", HANDOFF_ERRORS["training_design_withheld"])
        return decision_from_record(record, context)
