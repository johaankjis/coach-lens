# AWS-3: independent semantic evidence review

The Diagnostic Reasoner proposes a working diagnosis. AWS-3 reviews whether the **same provider-safe evidence population** supports that proposal. The review never generates a replacement cause or approves the diagnosis. Human approval, rejection, and revision remain M4 actions.

## Three distinct decisions

| Layer | Question | Authority |
| --- | --- | --- |
| Referential validation | Does the reference exist and belong here? | Deterministic Python checks before and after provider calls |
| Semantic validation | Does the evidence actually support the diagnosis? | Separate evidence validator call, recorded as a challenge or support assessment |
| Human validation | Does the expert approve, revise, or reject the working diagnosis? | M4 reviewer action; only this opens the M5 approval gate |

The semantic result is `supported`, `partially_supported`, `unsupported`, or `insufficient_evidence`. Only `supported` is labeled `evidence_validated`; the other outcomes are `evidence_questioned`. None changes the M4 `awaiting_review` status or counts as human approval. A reviewer may still approve, reject, or revise an unsupported proposal after inspecting it. The API offers `POST /diagnostics/hypotheses/{hypothesis_id}/validate-evidence` and `GET /diagnostics/hypotheses/{hypothesis_id}/evidence-validation`. Validation is an explicit on-demand step for currently proposed hypotheses.

## Inputs and wire boundary

The service saves the allowlisted evidence payload used for the successful M3 proposal. AWS-3 reuses its `signal`, complete `evidence_items` population, and `text_coverage`, then adds only `proposed_diagnosis` and `citation_roles`. References are opaque `SIGNAL-001` and `EVID-###`; local IDs and lineage stay in the process. Python checks the current bundle, citations, original mapping, lifecycle, and request keys before calling Bedrock. The validator may identify uncited passing evidence, since it receives the entire original provider-safe population.

The Converse user message is one JSON object with exactly these top-level keys:

| Key | Exact contents |
| --- | --- |
| `signal` | `reference`, `domain`, `criterion`, `failed_criterion_result_count`, `passed_criterion_result_count`, `evaluated_criterion_result_count`, `failure_rate`, `pass_rate`, `evaluations_containing_criterion`, `total_loaded_evaluations`, `feedback_count`, `feedback_coverage`, `max_score_total`, `attained_score_total`, `score_rate` |
| `evidence_items` | Complete original array; each item has `reference`, `domain`, `criterion`, `failed`, `max_score`, `attained_score` |
| `text_coverage` | `total_evidence_items`, `evidence_items_with_feedback`, `minimized_text_items_allowed`, `text_items_blocked`, `text_items_with_no_text` |
| `proposed_diagnosis` | `observed_behavioral_defect`, `cause_domain`, `performance_dimension`, `explanation`, `missing_evidence`, `provider_reported_confidence` |
| `citation_roles` | `supporting_reference_ids`, `conflicting_reference_ids` |

The separate system prompt states the review question, the meaning of every input field (including that counts and rates cover only evaluated criterion results and that `text_coverage` counts withheld local comments), the ResultsCX reasoning standard (a recurring failure proves what happened, not why; frequency alone does not establish a knowledge, skill, process, coaching, or training cause; uncited passing evidence can weaken a broad claim; claims about evaluator comments that were never supplied are unsupported; a restrained `undetermined` proposal with honest gaps is not penalized), the definition of each outcome, and a response contract rendered from `ValidatorResponse` with per-field guidance. Converse uses one user text block, temperature `0`, and `maxTokens` `1400`. Only `stopReason: end_turn` is accepted.

For trusted real ResultsCX workbooks, the AWS-2 structured-only projection is reused exactly. No real evaluator comment, minimized comment, answer, staff name, local ID, filename, sheet, path, row coordinate, `SourceLineage`, `Evaluation`, or `CriterionResult` is sent. The text coverage distinguishes local feedback withheld by policy from absent feedback. Proposed diagnostic prose is also screened against known local identifiers and comments before a second provider call. This is a narrow boundary, not a general PHI detector. A policy failure stops invocation and stores no validation.

The Bedrock validator uses a separate class, Converse call, system prompt, response schema, and request constructor from the Diagnostic Reasoner. Both may use Claude Sonnet 4.6; AWS-3 does not claim model diversity. The validator client defaults to `us-east-1` and `global.anthropic.claude-sonnet-4-6` and follows the configured Bedrock region and model ID. The locally stamped provider is Amazon Bedrock. **The global inference profile may route processing outside the `us-east-1` client region.**

The strict response has exactly seven required keys: `validation_outcome`, `support_assessment`, `supported_reference_ids`, `contradicting_reference_ids`, `unsupported_claims`, `missing_evidence`, and numeric `provider_reported_confidence` in `[0, 1]`. No metadata or replacement cause is accepted from the model. JSON parsing, Pydantic bounds, reference membership, duplicate/disjointness checks, and `end_turn` all fail closed. An outcome must also be grounded: `supported` and `partially_supported` need at least one supported reference, `unsupported` needs an unsupported claim or a contradicting reference, and `insufficient_evidence` needs a named gap. There is no output repair, semantic retry, or fixture fallback after Bedrock failure.

## Storage and traceability

One process-local immutable `EvidenceValidationRecord` is stored per hypothesis. Repeated POSTs return the same record and do not invoke the provider again, including after a human decision. It records the local validation/hypothesis/signal IDs, `assessed_proposal` (always `provider_hypothesis`), outcome, semantic status, assessment, confirmed and contradicting provider refs, unsupported claims, gaps, confidence, timestamp, and locally stamped provider/model/region/generation mode. The provider refs are also resolved through the saved local lookup into `supported_evidence` and `contradicting_evidence` (local `item_id`/`evaluation_id` references) so the review workspace opens the exact evaluation rows; the lookup is never serialized to Bedrock. A human revision is a different diagnosis: the stored review still describes the original proposal, and the workspace says so rather than presenting it as a review of the revision. Records disappear on process restart, like existing diagnostic and design state.

The installed default validator is unavailable unless Bedrock is enabled; it uses the configured Bedrock region and model ID. `install_results_cx_demo` installs a validator bound to the real-demo diagnostic service, and the synthetic smoke script runs one validation after its diagnosis. A controlled fixture adapter exists for tests only. The remote validator is gated to a diagnosis made by a bound synthetic or trusted ResultsCX Bedrock reasoner. A provider failure does not fall back to a fixture. Live AWS was not used for AWS-3 implementation tests.

## Limits and next review

Semantic outcomes are model judgments, not calibrated truth. A same-model second call reduces prompt and input coupling but does not provide model diversity. The review workspace loads any stored review for the selected proposal, can request one while the proposal is awaiting review, and shows the outcome, assessment, clickable confirmed and contradicting evidence, claims beyond the evidence, evidence still needed, and validator confidence beside the proposal and before the human decision. The on-demand API does not force reviewers to run semantic validation before M4 actions, preserving current M4 behavior. AWS-4 could define an explicit policy for whether a completed semantic review is required before human action, without granting the validator approval authority.
