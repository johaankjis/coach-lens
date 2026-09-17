"""Reject fabricated or cross-run references in untrusted design output."""

from pydantic import ValidationError

from app.diagnostics.engine import untrusted_payload

from .models import DesignInput, DecisionType, InterventionDecision, TrainingDesign


class InvalidDesignOutput(ValueError):
    pass


def _parse(model, raw):
    # The recursive reduction matters: a nested pre-built model instance inside a plain
    # mapping would otherwise skip validation and stay shared with the provider.
    try:
        return model.model_validate(untrusted_payload(raw))
    except (ValidationError, ValueError, TypeError) as exc:
        raise InvalidDesignOutput("Provider returned an invalid design artifact") from exc


def _unique(items, attribute, run_id):
    ids = [getattr(item, attribute) for item in items]
    if len(ids) != len(set(ids)) or any(not value.startswith(run_id + "/") for value in ids):
        raise InvalidDesignOutput("Duplicate or cross-run downstream identifier")
    return set(ids)


def _refs(values, allowed, label):
    if len(values) != len(set(values)) or not set(values) <= allowed:
        raise InvalidDesignOutput(f"Invalid {label} reference")


def validate_decision(raw: object, context: DesignInput) -> InterventionDecision:
    decision = _parse(InterventionDecision, raw)
    if decision.run_id != context.run_id or decision.diagnosis_id != context.approved.hypothesis_id:
        raise InvalidDesignOutput("Intervention provenance disagrees with approved diagnosis")
    _unique(decision.next_actions, "action_id", context.run_id)
    valid = {(r.item_id, r.evaluation_id) for r in context.allowed_evidence}
    refs = [(r.item_id, r.evaluation_id) for r in decision.evidence_refs]
    if len(refs) != len(set(refs)) or not set(refs) <= valid:
        raise InvalidDesignOutput("Intervention cites evidence outside approved diagnosis")
    if decision.decision_type == DecisionType.INVESTIGATE and not decision.unresolved_questions:
        raise InvalidDesignOutput("Investigation requires unresolved questions")
    return decision


def validate_training(raw: object, context: DesignInput) -> TrainingDesign:
    design = _parse(TrainingDesign, raw)
    if design.run_id != context.run_id or design.diagnosis_id != context.approved.hypothesis_id:
        raise InvalidDesignOutput("Training provenance disagrees with approved diagnosis")
    run = context.run_id
    behaviors = _unique(design.target_behaviors, "behavior_id", run)
    objectives = _unique(design.objectives, "objective_id", run)
    activities = _unique(design.activities, "activity_id", run)
    sections = _unique(design.outline, "section_id", run)
    scenarios = _unique(design.practice_scenarios, "scenario_id", run)
    checks = _unique(design.decision_checks, "check_id", run)
    all_ids = [*behaviors, *objectives, *activities, *sections, *scenarios, *checks]
    for check in design.decision_checks:
        all_ids.extend(option.option_id for option in check.options)
    for scenario in design.practice_scenarios:
        all_ids.append(scenario.persona.persona_id)
        all_ids.extend(beat.beat_id for beat in scenario.beats)
        all_ids.extend(criterion.criterion_id for criterion in scenario.rubric)
    if len(all_ids) != len(set(all_ids)) or any(not value.startswith(run + "/") for value in all_ids):
        raise InvalidDesignOutput("Downstream IDs must be globally unique within a run")
    for behavior in design.target_behaviors:
        if behavior.diagnosis_id != context.approved.hypothesis_id:
            raise InvalidDesignOutput("Target behavior references a different diagnosis")
    objective_by_id = {o.objective_id: o for o in design.objectives}
    for objective in design.objectives:
        _refs(objective.behavior_ids, behaviors, "target behavior")
    for activity in design.activities:
        _refs(activity.objective_ids, objectives, "activity objective")
    for section in design.outline:
        _refs(section.objective_ids, objectives, "outline objective")
        _refs(section.activity_ids, activities, "outline activity")
        for activity_id in section.activity_ids:
            activity = next(a for a in design.activities if a.activity_id == activity_id)
            if not set(activity.objective_ids) <= set(section.objective_ids):
                raise InvalidDesignOutput("Outline activity objectives disagree")
    for check in design.decision_checks:
        _refs(check.objective_ids, objectives, "check objective")
        if len({option.option_id for option in check.options}) != 4 or sum(o.correct for o in check.options) != 1:
            raise InvalidDesignOutput("Decision check requires four distinct options and one correct response")
    for scenario in design.practice_scenarios:
        if not scenario.persona.persona_id.startswith(run + "/"):
            raise InvalidDesignOutput("Cross-run persona reference")
        _refs(scenario.behavior_ids, behaviors, "practice behavior")
        _refs(scenario.objective_ids, objectives, "practice objective")
        if scenario.activity_id not in activities:
            raise InvalidDesignOutput("Practice activity does not exist")
        activity = next(a for a in design.activities if a.activity_id == scenario.activity_id)
        if not set(scenario.objective_ids) <= set(activity.objective_ids):
            raise InvalidDesignOutput("Practice and activity objectives disagree")
        if not set(scenario.behavior_ids) <= {behavior_id for objective_id in scenario.objective_ids
                                              for behavior_id in objective_by_id[objective_id].behavior_ids}:
            raise InvalidDesignOutput("Practice behavior is not supported by its objectives")
        _unique(scenario.beats, "beat_id", run)
        _unique(scenario.rubric, "criterion_id", run)
        for criterion in scenario.rubric:
            if criterion.behavior_id not in scenario.behavior_ids or criterion.objective_id not in scenario.objective_ids:
                raise InvalidDesignOutput("Rubric references outside practice")
            if criterion.behavior_id not in objective_by_id[criterion.objective_id].behavior_ids:
                raise InvalidDesignOutput("Rubric breaks behavior-objective traceability")
        # A behavior the practice claims to exercise but no criterion observes is unscorable.
        if not {criterion.behavior_id for criterion in scenario.rubric} >= set(scenario.behavior_ids):
            raise InvalidDesignOutput("Practice behavior has no rubric criterion")
    # Coverage checks below are reference integrity only: every artifact must be reachable
    # from the outline and every claimed behavior must be practiced and have a rubric criterion. Whether the
    # content is pedagogically sound is M6's independent judgement, not established here.
    if not all(any(o.objective_id in a.objective_ids for a in design.activities) for o in design.objectives):
        raise InvalidDesignOutput("Every objective needs a proposed activity")
    if not all(any(b.behavior_id in o.behavior_ids for o in design.objectives) for b in design.target_behaviors):
        raise InvalidDesignOutput("Every target behavior needs an objective")
    scheduled = {activity_id for section in design.outline for activity_id in section.activity_ids}
    if not scheduled >= activities:
        raise InvalidDesignOutput("Every activity must appear in the training outline")
    practiced = {behavior_id for scenario in design.practice_scenarios for behavior_id in scenario.behavior_ids}
    if not practiced >= behaviors:
        raise InvalidDesignOutput("Every target behavior needs hands-on practice")
    return design
