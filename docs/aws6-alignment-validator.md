# AWS-6: Independent Training Alignment Validator

AWS-6 answers one question about a stored AWS-5 training package: does it actually address the human-confirmed performance gap and the solution-validated intervention it was designed from? It is one independent Amazon Bedrock call over the stored package, `POST /designs/diagnoses/{hypothesis_id}/alignment-review`, that returns a strict semantic verdict and stores it as one immutable `AlignmentReview` per design run. It does not diagnose, decide the intervention, generate or edit training, or measure outcomes. Those remain M3/M4, AWS-4, AWS-5, and later work.

```
ResultsCX QA -> deterministic signal -> AWS-1 diagnosis -> AWS-3 evidence review -> M4 human validation
  -> AWS-4 intervention + solution validation -> AWS-5 training design -> structural_references_only trace
  -> AWS-6 alignment review (this document)                       app/design/alignment_*.py
  -> design_aligned | design_questioned                            ready for deployment / outcome measurement
```

## Structural (AWS-5) versus semantic (AWS-6)

AWS-5's `AlignmentTrace` is built locally from the validated package and carries `assessment: structural_references_only`. It proves that every target behavior, objective, activity, practice scenario, rubric criterion, and knowledge check exists, is unique to the run, and references only elements that exist. It says nothing about meaning. A package whose gap is "does not clearly explain resolution options", whose target behavior is "accurately document the call", whose objective is "document interaction fields correctly", and whose activity is a documentation worksheet passes every structural check.

AWS-6 reads that same stored package and judges whether the meaning of each downstream element supports the upstream need. It does not trust or repeat the structural trace; the trace only guarantees that the labels AWS-6 is given resolve to real elements. The stored review restates `structural_trace: structural_references_only` so the two checks are never confused in the record or the UI.

## Semantic chain reviewed

| Dimension | Question |
| --- | --- |
| `gap_to_target_behavior` | Would performing each target behavior correct the confirmed performance problem? |
| `target_behavior_to_objective` | Would meeting each objective demonstrate its target behavior? |
| `objective_to_activity` | Does each activity teach or practice the objectives it names? |
| `objective_to_knowledge_check` | Does each decision check assess the judgment the objectives require, not unrelated recall? `not_applicable` only when the package has no check (AWS-5 provider packages always have one; the M5 contract allows none). |
| `target_behavior_to_practice` | Does the scripted scenario require the learner to perform the target behaviors, turn by turn? |
| `practice_to_rubric` | Does each rubric criterion score the behavior the learner is meant to demonstrate? |
| `intervention_to_package` | Taken together, does the package implement the validated intervention's recommendation and target change, and nothing else? |

## Input: the provider-safe view

`build_alignment_view` (`app/design/alignment_review.py`) is an explicit allowlist over the stored `DesignResult`; nothing is `model_dump`ed. The user message has exactly three keys:

- `confirmed_performance_gap`: `reference` `GAP-001`, `qa_criterion`, `observed_behavior`, `confirmed_cause_domain`, `performance_dimension`, `cause_explanation`, `human_revised`, from the approved diagnosis.
- `validated_intervention`: `reference` `INT-001`, `intervention_type`, `recommendation`, `target_change`, `rationale`, from the stored AWS-4 decision the design ran on.
- `training_package`: `performance_context`, `target_behaviors`, `objectives` (with condition, observable action, standard), `activities`, `knowledge_checks` (options without IDs), `practice_scenarios` (persona without name, scripted turns, completion criteria, rubric, escalation expectation), `supplied_operational_context`, `missing_operational_details`.

Element identifiers are reduced to their short local labels (`B1`, `O1`, `A1`, `K1`, `P1`, `BEAT1`, `R1`), which are unique within a validated package; the run prefix never travels. The view records a `design_digest` of the exact package it was built from. The outline schedule, durations, persona names, option IDs, and debrief prompts are not needed to judge alignment and are not sent.

A design whose decision lacks the AWS-4 handoff fields (the controlled M5 fixture decision) has no validated intervention to align against and is refused with `alignment_review_not_permitted` (409) before any call. A non-training result is refused with `no_training_design` (409).

## Output contract

`BedrockAlignmentValidator` (`app/design/alignment_bedrock.py`) follows the AWS-1/AWS-3/AWS-4/AWS-5 pattern: Bedrock Runtime `Converse`, `us-east-1` and `global.anthropic.claude-sonnet-4-6` by default (following `COACHLENS_BEDROCK_REGION` / `COACHLENS_BEDROCK_MODEL_ID`), temperature `0`, one system prompt (instructions plus `response_contract()` rendered from the `AlignmentResponse` schema), one user text block, `maxTokens` 4000, explicit timeouts, standard retries. The model must return exactly one JSON object:

```
overall_outcome            aligned | partially_aligned | misaligned | insufficient_information
overall_assessment         text
dimensions                 exactly the seven keys above, each {outcome, assessment, misaligned_element_ids}
unsupported_assumptions    [text]
missing_information        [text]
provider_reported_confidence   JSON number 0..1
```

Fail-closed rules (`parse_alignment_response`): JSON must parse to one object with no duplicate keys; only `stopReason: end_turn`; every key required at every level, no extras (a `status`, `provider`, `run_id`, `training_design`, `revised_objectives`, or any other key is refused); strict primitive types, no coercion (`"0.8"`, `"high"`, `true`, or `1.5` for confidence are refused; `"A1"` instead of `["A1"]` is refused); no blank text; every `misaligned_element_ids` entry must be a label that exists in the stored package, unique within its list, and of a kind that dimension can name (a rubric criterion under the gap link, an option, a persona, an outline section, or a run-prefixed identifier is an impossible reference); an `aligned` or `not_applicable` dimension names no elements; `not_applicable` is valid for the knowledge-check dimension exactly when the package has no check and for no other dimension; overall `aligned` requires every applicable dimension `aligned`, no misaligned elements, and no unsupported assumptions; overall `misaligned` requires a `misaligned` dimension; overall `partially_aligned` requires at least one aligned dimension and something questioned; overall `insufficient_information` requires `missing_information`. There is no repair, retry, or fixture fallback.

The stored `AlignmentReview` resolves labels back to the run-prefixed stored identifiers and adds: `alignment_review_id`, `run_id`, `diagnosis_id`, `intervention_id`, `solution_validation_id`, `design_digest`, `assessed: training_design_package`, `structural_trace: structural_references_only`, `design_status`, and locally stamped `provider_metadata` (Amazon Bedrock, model, region, `generation_mode` from the installed object) with `created_at`. It carries no copy of design content.

## State and gating

- `design_status` is `design_aligned` only for overall `aligned`; `partially_aligned`, `misaligned`, and `insufficient_information` are `design_questioned`. Nothing is labelled deployed, effective, or outcome-validated.
- One immutable review per design run, keyed like the design. A repeated `POST` returns the stored record without another provider call; `GET /designs/diagnoses/{hypothesis_id}/alignment-review` returns it or `alignment_review_not_found` (404).
- A failed, refused, malformed, unavailable (`alignment_validator_unavailable`, 503), or privacy-blocked call stores nothing and may be retried.
- The review never writes to the design service. `DesignResult.status` stays `ready_for_alignment_review` and the structural trace is untouched. The review is bound to the package by `design_digest`; a package that differs from the reviewed one reports `alignment_review_stale` (409).
- Every read and write goes through `DesignService.get`, so the M3 approval gate and the design-run requirement are re-run each time.

`/diagnostics/mode` reports `alignment_validator` from the installed object (`unavailable`, `controlled_fixture`, or `provider`). `app/pipeline.py` installs `AlignmentReviewService` over the same design service for both startup paths; with `COACHLENS_BEDROCK_ENABLED=false` it is unavailable, with `true` it is the Bedrock adapter bound to the installed diagnostic service.

## Privacy (AWS-2 preserved)

The request carries no evaluator, agent, or leader name, no evaluator comment, no row, evaluation, item, or evidence reference, no source lineage, filename, sheet, or workbook, no run, diagnosis, hypothesis, signal, intervention, or solution-validation identifier, no outcome label or gate value, and no count, rate, score, or duration. Tests assert the allowlist keys and that known synthetic identifiers never appear on the wire.

Before invocation the adapter requires a bound `DiagnosticService` whose reasoner declares `local_fixture`, `synthetic_only`, or `real_minimized`; otherwise, or without a bound service, it blocks with `alignment_privacy_blocked` (502) before any client exists. It then screens every string in the request, including the AWS-5 generated package text (which AWS-5 stores unscreened), with the AWS-3 local screen against known names, local identifiers, filenames, sheets, and verbatim comments, and blocks on a hit. This is a narrow boundary, not PHI detection.

## UI

The existing design workspace gains one restrained section, "Alignment Check · AI semantic design review". Before a review exists it explains that the AWS-5 trace only proves references and offers **CHECK ALIGNMENT**; afterwards it shows `DESIGN ALIGNED` or `DESIGN QUESTIONED` with the overall outcome, the assessment, the validator-reported confidence (explicitly non-calibrated), the seven dimensions with flagged elements, problematic design elements, unsupported assumptions, missing information, and the review origin. The design status line changes to the review verdict; the package itself renders unchanged. A stored review is loaded whenever a training package is shown. The Home / Command Center branch is not touched.

## Smoke

`scripts/run_bedrock_synthetic_smoke.py` runs AWS-6 after a generated package (`--skip-alignment` stops before it) and prints outcomes, counts, and provenance only. The automated suite drives it with stub Converse clients; live AWS was not used for this implementation.

## Limits

The verdict quality depends on the model; the contract enforces structure, reference integrity, and outcome coherence, not the correctness of the semantic judgement. The review is a hypothesis for a human, not an approval. It does not run the simulation, score a learner, measure outcomes, or claim deployment. Results live in process memory. Bedrock native structured outputs are not used, for the reasons recorded in the AWS-1 guide.
