# Architecture principles

The repository implements deterministic QA analysis (M2), diagnosis and review (M3–M4), and proposed intervention/training orchestration (M5). These ownership boundaries remain in force.

## Deterministic code owns quantitative truth

Code calculates and validates counts, percentages, frequencies, aggregations, joins, trends, and cost calculations. It also checks source data and derived results. Models must not invent or silently replace these calculations.

## AI models interpret and generate

Models may interpret QA comments, propose root-cause hypotheses, explain evidence, reason about interventions, and draft scenarios or training content. Their output should be presented as interpretation or generated material, tied to deterministic facts and source evidence.

## Humans validate consequential decisions

Humans approve or correct diagnoses before M5 design can run. M5 intervention and training artifacts are proposals, not approved decisions. A later alignment/design review must precede consequential use. The workflow retains reviewer corrections alongside the evidence they reviewed.

## Evidence lineage

M2–M5 contracts preserve references from source QA records through validated calculations, diagnosis hypotheses, human decisions, interventions, and training artifacts. This lineage makes structural provenance inspectable; M6 will evaluate actual design alignment and later outcome measurements against the original evidence.
