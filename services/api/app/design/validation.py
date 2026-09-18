"""Reject fabricated or cross-run references in untrusted design output."""

import re

from pydantic import ValidationError

from app.diagnostics.engine import untrusted_payload

from .models import DesignInput, DecisionType, InterventionDecision, TrainingDesign


# A designer marks an operational fact it was not given with this token instead of inventing
# one. Every token must be declared in `missing_operational_details`.
PLACEHOLDER_PATTERN = re.compile(r"\[PLACEHOLDER:[^\]]*\]")


def _texts(value) -> list[str]:
    """Every string anywhere in a validated design, for whole-design text checks."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _texts(item)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _texts(item)]
    return []


class InvalidDesignOutput(ValueError):
    pass


def _parse(model, raw):
    # The recursive reduction matters: a nested pre-built model instance inside a plain
    # mapping would otherwise skip validation and stay shared with the provider.
    try:
        parsed = model.model_validate(untrusted_payload(raw))
    except (ValidationError, ValueError, TypeError) as exc:
        raise InvalidDesignOutput("Provider returned an invalid design artifact") from exc
    if parsed.provider_metadata.generation_mode is not None:
        # `DesignResult.generation_mode` is service-assigned; the shared metadata field may
        # not be used by a provider or fixture to describe itself.
        raise InvalidDesignOutput("Provider may not assert its generation mode")
    return parsed


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
    details = _unique(design.missing_operational_details, "detail_id", run)
    all_ids = [*behaviors, *objectives, *activities, *sections, *scenarios, *checks, *details]
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
        # ResultsCX: feedback is specific to each option. Identical feedback on two options,
        # or feedback that merely restates the response, is not specific.
        feedback = [option.feedback.strip().casefold() for option in check.options]
        if len(set(feedback)) != 4 or any(option.feedback.strip().casefold() == option.response.strip().casefold()
                                          for option in check.options):
            raise InvalidDesignOutput("Decision check feedback must be specific to each option")
        _refs(check.behavior_ids, {behavior_id for objective_id in check.objective_ids
                                   for behavior_id in objective_by_id[objective_id].behavior_ids},
              "check behavior")
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
        for beat in scenario.beats:
            _refs(beat.behavior_ids, set(scenario.behavior_ids), "beat behavior")
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
    # AWS-5: the design basis is a local restatement of the approved diagnosis, so it must
    # agree with the gate exactly. A provider cannot re-describe the gap it was given.
    basis = design.design_basis
    if basis is not None:
        approved = context.approved
        if (basis.gap.diagnosis_id != approved.hypothesis_id or basis.gap.signal_id != approved.signal_id or
                basis.gap.observed_behavior != approved.diagnosis.observed_behavioral_defect or
                basis.gap.cause_domain != approved.diagnosis.cause_domain or
                basis.gap.performance_dimension != approved.diagnosis.performance_dimension or
                basis.gap.human_revised != approved.human_revised or basis.intervention.run_id != run):
            raise InvalidDesignOutput("Design basis disagrees with the approved diagnosis")
    # Every placeholder token in the design must be a declared missing operational detail, so
    # nothing is silently left as a gap and nothing undeclared can pose as supplied fact.
    declared = {detail.placeholder for detail in design.missing_operational_details}
    if any(not PLACEHOLDER_PATTERN.fullmatch(placeholder) for placeholder in declared) or len(declared) != len(details):
        raise InvalidDesignOutput("Missing operational details need distinct placeholder tokens")
    used = {token for text in _texts(design.model_dump(mode="python", exclude={"missing_operational_details"}))
            for token in PLACEHOLDER_PATTERN.findall(text)}
    if not used <= declared:
        raise InvalidDesignOutput("Undeclared placeholder in training design")
    return design
