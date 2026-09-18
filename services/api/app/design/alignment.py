"""Mechanical alignment trace for the AWS-6 handoff.

The trace enumerates every validated-gap -> intervention -> target behavior -> objective ->
activity -> practice -> rubric path that the structural validator already proved consistent.
It is built from the stored design, never from provider output, and it judges nothing: AWS-6
decides whether those references are semantically aligned.
"""

from .models import (AlignmentLink, AlignmentTrace, InterventionDecision, KnowledgeCheckLink,
                     TrainingDesign)


def build_alignment_trace(design: TrainingDesign, decision: InterventionDecision) -> AlignmentTrace:
    objective_by_id = {objective.objective_id: objective for objective in design.objectives}
    links = tuple(AlignmentLink(diagnosis_id=design.diagnosis_id, intervention_run_id=decision.run_id,
                                behavior_id=criterion.behavior_id, objective_id=criterion.objective_id,
                                activity_id=scenario.activity_id, scenario_id=scenario.scenario_id,
                                criterion_id=criterion.criterion_id)
                  for scenario in design.practice_scenarios for criterion in scenario.rubric)
    checks = tuple(KnowledgeCheckLink(check_id=check.check_id, objective_id=objective_id,
                                      behavior_ids=objective_by_id[objective_id].behavior_ids)
                   for check in design.decision_checks for objective_id in check.objective_ids)
    return AlignmentTrace(run_id=design.run_id, diagnosis_id=design.diagnosis_id, links=links,
                          knowledge_check_links=checks,
                          missing_operational_detail_ids=tuple(d.detail_id for d in design.missing_operational_details))
