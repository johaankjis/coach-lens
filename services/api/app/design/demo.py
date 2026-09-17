"""Controlled synthetic M5 outputs. Not an AI provider or production default."""


PROVIDER = {"provider": "m5-demo-fixture", "model": None}


class DemoDesignFixture:
    """Fixed synthetic outputs keyed only on the signal ID it was constructed with.

    No inference and no cause-domain rule: the branch is a demo configuration choice.
    """

    def __init__(self, training_signal_id: str, alternative: str = "investigate"):
        self.training_signal_id = training_signal_id
        self.alternative = alternative

    async def decide(self, context):
        training = context.approved.signal_id == self.training_signal_id
        kind = "training" if training else self.alternative
        run = context.run_id
        return {
            "run_id": run, "diagnosis_id": context.approved.hypothesis_id,
            "decision_type": kind,
            "rationale": ("Synthetic proposal: rehearse an observable resolution summary with a member."
                          if training else "Synthetic proposal: current all-pass QA evidence does not justify training."),
            "evidence_refs": [context.allowed_evidence[0].model_dump()],
            "risks": ["Synthetic QA evidence may not represent other calls."],
            "unresolved_questions": (["Collect failed examples or direct observation before selecting an intervention."]
                                     if kind == "investigate" else []),
            "next_actions": [{"action_id": run + "/N1", "title": ("Review proposed training" if training else "Review operational evidence"),
                              "instructions": ("Submit the design to independent alignment review."
                                               if training else "Collect observations and revisit the diagnosis.")}],
            "provider_metadata": dict(PROVIDER),
        }

    async def design(self, context, decision):
        run = context.run_id
        b, o, a = (run + suffix for suffix in ("/B1", "/O1", "/A1"))
        return {
            "run_id": run, "diagnosis_id": context.approved.hypothesis_id,
            "performance_context": "Human-validated synthetic diagnosis: missed resolution-summary clarity on three of four QA results. The proposed training is not yet alignment-reviewed.",
            "target_behaviors": [{"behavior_id": b, "diagnosis_id": context.approved.hypothesis_id,
                                  "description": "State the resolution and next action in plain language, then ask the member to confirm the next step."}],
            "objectives": [{"objective_id": o, "behavior_ids": [b],
                            "measurable_outcome": "In a simulated call, summarize resolution, name the next action, and confirm member understanding before closing."}],
            "activities": [{"activity_id": a, "activity_type": "guided_simulation",
                            "purpose": "Practice a complete, observable closing sequence.",
                            "instructions": "Handle the synthetic member's unresolved follow-up question, then deliver and verify the closing summary.",
                            "objective_ids": [o], "expected_learner_behavior": "States resolution and next action; checks understanding.",
                            "success_indicator": "All three elements are audible before closing.", "duration_minutes": 12}],
            "outline": [{"section_id": run + "/S1", "title": "Model a clear resolution summary",
                         "purpose": "Show the target closing behavior.", "duration_minutes": 8,
                         "objective_ids": [o], "activity_ids": []},
                        {"section_id": run + "/S2", "title": "Rehearse the closing sequence",
                         "purpose": "Apply the behavior under a realistic member challenge.", "duration_minutes": 12,
                         "objective_ids": [o], "activity_ids": [a]}],
            "decision_checks": [{"check_id": run + "/K1", "objective_ids": [o],
                                 "situation": "A member asks what happens after the case is updated.",
                                 "question": "Which response best completes the closing sequence?",
                                 "options": [
                                     {"option_id": run + "/K1_OPT1", "response": "The case is updated. Goodbye.", "feedback": "This omits the next action and understanding check.", "correct": False},
                                     {"option_id": run + "/K1_OPT2", "response": "Your case is updated; you will receive a message tomorrow. Can you tell me what you expect next?", "feedback": "This names resolution, next action, and checks understanding.", "correct": True},
                                     {"option_id": run + "/K1_OPT3", "response": "You can call back if needed.", "feedback": "This does not explain the expected follow-up.", "correct": False},
                                     {"option_id": run + "/K1_OPT4", "response": "The team will handle it.", "feedback": "This is too vague to confirm the next action.", "correct": False}] }],
            "practice_scenarios": [{"scenario_id": run + "/P1", "title": "Confirm a follow-up resolution",
                "call_driver": "Synthetic member seeks clarity on a resolved service request.", "learner_role": "Service representative",
                "persona": {"persona_id": run + "/PERSONA1", "name": "Morgan (synthetic)",
                    "context": "Has been told a request was updated but is unsure what happens next.",
                    "communication_style": "Direct and asks short follow-up questions.", "emotional_state": "Mildly frustrated",
                    "knows": "A request was submitted.", "wants": "A precise next step and timing.",
                    "withholding": "Does not volunteer that the earlier explanation was confusing unless asked.",
                    "success_response": "Restates the next step and agrees to close.",
                    "failure_response": "Asks what will happen next and resists closing."},
                "learner_objective": "Deliver and verify a complete resolution summary.",
                "opening_line": "I heard it was updated, but what exactly happens now?",
                "behavior_ids": [b], "objective_ids": [o], "activity_id": a,
                "beats": [{"beat_id": run + "/BEAT1", "trigger": "Learner explains the update.",
                           "likely_response": "So do I need to call again?", "success_branch": "If next action is specific, ask for timing.",
                           "challenge_branch": "If vague, repeat the question and express concern."}],
                "completion_criteria": ["Learner states resolution, next action, and confirms understanding before closing."],
                "rubric": [{"criterion_id": run + "/R1", "behavior_id": b, "objective_id": o,
                            "practice_behavior": "Summarize resolution and next action, then check understanding.",
                            "observable_success": "All three components occur before close, with a member response to the check.",
                            "scoring_guidance": "Met only when resolution, specific next action, and understanding check are explicit; otherwise not met."}],
                "debrief_prompts": ["Which phrase made the next action clear?", "What did the member say after the understanding check?"]}],
            "provider_metadata": dict(PROVIDER),
        }
