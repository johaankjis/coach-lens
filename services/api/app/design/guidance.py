"""Compact, versioned ResultsCX instructional-design guidance for the Training Designer.

This is the methodology layer only. It never contains QA evidence or generated content.
This follows the diagnosis and design principles recorded in the repository's M3 and M5
documentation. It does not assert an undocumented ResultsCX template sequence. Bump the
version whenever the wording changes so a stored design records which guidance produced it.
"""

GUIDANCE_VERSION = "resultscx-design-guidance/2"

# The structural chain M5 documents. These are artifact relationships, not an imported
# ResultsCX template or a claim that the output is semantically aligned.
DESIGN_CHAIN = (
    "human-approved diagnosis",
    "proposed intervention",
    "target behavior",
    "objective",
    "activity",
    "practice scenario",
    "rubric criterion",
)

PRINCIPLES = (
    "QA Needs Analysis is diagnostic: it establishes what happened and, once validated, why.",
    "AI findings are hypotheses until a human validates them.",
    "Root cause must be confirmed before Design begins.",
    "The training solution outline must map to the confirmed root cause, not to the symptom alone.",
    "Every target behavior must be observable: something a facilitator can see or hear the learner do.",
    "Every assessment must be measurable: a standard that can be met or not met without interpretation.",
    "The simulation rubric operationalizes competent performance of the target behavior.",
    "Training can look polished and still be misaligned; polish is not evidence of alignment.",
    "Knowledge checks are decision-based: a realistic situation, a decision, exactly four options, "
    "one correct, and feedback that is specific to each option.",
)

KNOWLEDGE_CHECK_RULES = (
    "Present a realistic situation and ask which decision or response the learner would make.",
    "Exactly four options. Exactly one is correct.",
    "Feedback is specific to each option: it explains why that option is or is not the right decision.",
    "Each check traces to at least one objective, and through it to a target behavior.",
)

PRACTICE_RULES = (
    "Practice is hands-on: a scripted simulation the learner performs, not a description of role play.",
    "Specify the scenario setup, the learner role, a fictional member persona, an opening line, "
    "conversational turns with the expected learner behavior at each turn, and facilitator cues.",
    "The rubric scores the target behaviors the practice exercises; every criterion names a behavior "
    "and an objective and states what observable success looks like.",
    "Do not invent operational policies, escalation contacts, healthcare or benefit facts, system "
    "steps, or procedures that were not supplied. Where the design needs such a detail, write a "
    "placeholder token and list it as a missing operational detail.",
)


def guidance_text() -> str:
    """Render the guidance as prompt text. Kept short so it fits every request unchanged."""
    lines = [f"ResultsCX design guidance ({GUIDANCE_VERSION}).",
             "Documented design chain: " + " -> ".join(DESIGN_CHAIN) + ". You produce the "
             "design artifacts for one confirmed gap; the diagnosis and intervention are upstream.",
             "Principles:"]
    lines.extend(f"- {principle}" for principle in PRINCIPLES)
    lines.append("Knowledge check rules:")
    lines.extend(f"- {rule}" for rule in KNOWLEDGE_CHECK_RULES)
    lines.append("Hands-on practice rules:")
    lines.extend(f"- {rule}" for rule in PRACTICE_RULES)
    return "\n".join(lines)
