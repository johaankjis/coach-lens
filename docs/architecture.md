# Architecture principles

Milestone 1 establishes the repository layout without implementing the diagnosis or training pipeline. Later capabilities should follow these ownership boundaries.

## Deterministic code owns quantitative truth

Code calculates and validates counts, percentages, frequencies, aggregations, joins, trends, and cost calculations. It also checks source data and derived results. Models must not invent or silently replace these calculations.

## AI models interpret and generate

Models may interpret QA comments, propose root-cause hypotheses, explain evidence, reason about interventions, and draft scenarios or training content. Their output should be presented as interpretation or generated material, tied to deterministic facts and source evidence.

## Humans validate consequential decisions

Humans approve or correct diagnoses and approve interventions before consequential decisions are used downstream. The workflow must retain those choices and corrections alongside the evidence they reviewed.

## Evidence lineage

Future data contracts and artifacts must preserve references from source QA records through validated calculations, diagnosis hypotheses, human decisions, interventions, and training artifacts. This lineage should make each claim inspectable and allow later outcome measurements to be compared with the original evidence. The current repository does not yet define those contracts or ingest records.
