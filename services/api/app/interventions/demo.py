"""Controlled synthetic AWS-4 outputs for the M4 demo. Not an AI provider or production default.

The branch is a demo configuration keyed on the synthetic criterion wording, exactly like the
M5 `DemoDesignFixture` is keyed on a signal ID. No inference and no cause-to-intervention
rule is applied; every fixed response still passes the real strict parsers.
"""

from copy import deepcopy


RESOLUTION_CRITERION = "Resolution summary clarity"
PROCESS_CRITERION = "Required follow-up prompt available in workflow"


class DemoInterventionFixture:
    """Fixed intervention proposals for the three synthetic M4 demo signals."""

    controlled_fixture = True  # Reported by /diagnostics/mode from the object, not a label.

    def __init__(self):
        self.requests: list[dict] = []

    async def propose(self, request: dict) -> dict:
        self.requests.append(deepcopy(request))
        roles = request["citation_roles"]
        cited = roles["supporting_reference_ids"] + roles["conflicting_reference_ids"]
        if request["signal"]["criterion"] == RESOLUTION_CRITERION:
            return {
                "intervention_type": "practice_simulation",
                "recommendation": "Synthetic proposal: rehearse the closing sequence in short simulated calls "
                                  "with feedback, rather than a classroom module.",
                "rationale": "Synthetic fixed text: the human-validated diagnosis names a skill gap in "
                             "capability, so rehearsal with feedback fits better than instruction alone.",
                "target_change": "State the resolution and the next action in plain language, then ask the "
                                 "member to confirm the next step before closing.",
                "fit_to_cause": "A skill gap where the agent cannot yet perform the behavior reliably "
                                "calls for practice; frequency alone did not select this intervention.",
                "evidence_reference_ids": cited[:1],
                "limitations": ["Synthetic QA evidence may not represent other calls."],
                "missing_evidence": ["Direct observation of the agent's explanation process."],
                "provider_reported_confidence": 0.6,
            }
        if request["signal"]["criterion"] == PROCESS_CRITERION:
            return {
                "intervention_type": "process_correction",
                "recommendation": "Synthetic proposal: add the required follow-up prompt to the approved workflow and verify that it appears at the right step.",
                "rationale": "Synthetic fixed text: the validated cause is a missing workflow prompt, so changing the workflow addresses the gap directly; repeating agent training does not add the prompt.",
                "target_change": "The approved workflow displays the required follow-up prompt before the agent closes the case.",
                "fit_to_cause": "A process gap requires a process correction; failure frequency alone does not establish a training need.",
                "evidence_reference_ids": cited[:1],
                "limitations": ["The fixed diagnosis assumes the workflow audit reflects the current approved version."],
                "missing_evidence": ["Confirm the prompt appears in the deployed workflow."],
                "provider_reported_confidence": 0.6,
            }
        return {
            "intervention_type": "investigate_further",
            "recommendation": "Synthetic proposal: collect failed examples or direct observation before "
                              "selecting an intervention.",
            "rationale": "Synthetic fixed text: the human-validated diagnosis is undetermined and the "
                         "structured evidence shows no failures, so no intervention is justified yet.",
            "target_change": "Establish whether any follow-up documentation problem exists before "
                             "changing agent behavior or process.",
            "fit_to_cause": "An undetermined cause with all-pass evidence calls for investigation, not "
                            "training, coaching, or a process change.",
            "evidence_reference_ids": cited[:1],
            "limitations": ["The synthetic population is small."],
            "missing_evidence": ["Failed criterion rows or direct observation."],
            "provider_reported_confidence": 0.5,
        }


class DemoSolutionFixture:
    """Fixed solution reviews for the fixed proposals above."""

    controlled_fixture = True

    def __init__(self):
        self.requests: list[dict] = []

    async def validate(self, request: dict) -> dict:
        self.requests.append(deepcopy(request))
        proposed = request["proposed_intervention"]["intervention_type"]
        cause = request["validated_diagnosis"]["cause_domain"]
        if proposed == "practice_simulation" and cause == "skill_gap":
            return {"alignment_outcome": "aligned",
                    "alignment_assessment": "Synthetic fixed review: practice with feedback addresses a "
                                            "validated skill gap, and the target change matches the observed "
                                            "closing-clarity defect.",
                    "aligned_points": ["Intervention type fits a capability skill gap",
                                       "Target change addresses the observed defect"],
                    "misaligned_points": [], "unsupported_assumptions": [],
                    "missing_information": ["Direct observation would confirm the skill gap"],
                    "provider_reported_confidence": 0.65}
        if proposed == "process_correction" and cause == "process_gap":
            return {"alignment_outcome": "aligned",
                    "alignment_assessment": "Synthetic fixed review: adding the missing prompt addresses the validated workflow cause; agent training alone would leave the process unchanged.",
                    "aligned_points": ["The change corrects the validated workflow gap",
                                       "The target change names the prompt to add"],
                    "misaligned_points": [], "unsupported_assumptions": [],
                    "missing_information": [], "provider_reported_confidence": 0.7}
        if proposed == "investigate_further" and cause == "undetermined":
            return {"alignment_outcome": "aligned",
                    "alignment_assessment": "Synthetic fixed review: investigation is the appropriate "
                                            "response to an undetermined cause with all-pass evidence.",
                    "aligned_points": ["Investigation matches the undetermined cause"],
                    "misaligned_points": [], "unsupported_assumptions": [],
                    "missing_information": [], "provider_reported_confidence": 0.7}
        # Any other pairing (for example a reviewer-revised process gap met with practice) is
        # questioned by this fixed fixture rather than approved.
        return {"alignment_outcome": "misaligned",
                "alignment_assessment": "Synthetic fixed review: the proposed intervention type does not "
                                        "address the human-validated cause.",
                "aligned_points": [],
                "misaligned_points": [f"{proposed} does not address a {cause}"],
                "unsupported_assumptions": [],
                "missing_information": [], "provider_reported_confidence": 0.6}
