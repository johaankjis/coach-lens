# AWS-4: Intervention Reasoner and Solution Validator

AWS-4 starts where M4 human validation ends. It answers two distinct questions about one human-validated diagnosis, with two separate Bedrock calls, two strict contracts, and two immutable records, and it hands a typed decision to M5/AWS-5 that says whether training design may run at all.

```
ResultsCX QA -> M2 signals -> Bedrock Diagnostic Reasoner (AWS-1/AWS-2)
  -> AWS-3 Semantic Evidence Validator -> M4 human Approve / Reject / Revise
  -> [AWS-4] Intervention Reasoner -> Solution Validator
  -> M5 handoff -> AWS-5 training design only when the validated intervention calls for training or practice
```

State progression: `PROPOSED DIAGNOSIS -> EVIDENCE VALIDATED | QUESTIONED -> HUMAN VALIDATED -> INTERVENTION PROPOSED -> SOLUTION VALIDATED | QUESTIONED`. The human decision is the diagnosis approval; nothing in AWS-4 is a human decision, and nothing in AWS-4 can change the diagnosis.

## Why CoachLens does not automatically prescribe training

A performance problem shows *what* happened. The ResultsCX Needs Analysis distinguishes *why*: a knowledge gap, a skill gap, a process gap, or an execution issue where the agent could perform the behavior but did not, and it allows *undetermined* when the evidence cannot say. Each of those points somewhere different: knowledge reinforcement or training, practice or simulation or coaching, workflow or SOP or system correction, supervisor coaching or reinforcement, or further investigation. Failure count, failure rate, recurrence, and score rate never choose among them, and approving a diagnosis is not approving training. AWS-4 therefore makes the intervention an explicit reasoning step with five typed outcomes, then asks a second, separate reviewer whether the chosen intervention actually addresses the human-validated cause, and only lets a training or practice proposal that survived that review reach the training generator. There is no cause-to-intervention lookup in code: the reasoner chooses from the validated diagnosis and the evidence, deterministic code checks structure, references, lifecycle, and provenance.

## Intervention Reasoner

`POST /interventions/diagnoses/{hypothesis_id}/propose` runs the M3 `get_approved_diagnosis()` gate, rebuilds and re-verifies the exact provider-safe evidence population saved for the diagnosis, projects the human-validated diagnosis, and invokes the reasoner once. The Converse user message is one JSON object with exactly these keys:

| Key | Contents |
| --- | --- |
| `signal`, `evidence_items`, `text_coverage` | The AWS-2/AWS-3 provider-safe population, byte-for-byte the projection the Diagnostic Reasoner received (structured facts, opaque `SIGNAL-001` and `EVID-###` references, withheld-comment counts) |
| `validated_diagnosis` | `observed_behavioral_defect`, `cause_domain`, `performance_dimension`, `explanation`, `missing_evidence` of the **approved diagnosis**: the reviewer's revision when one was approved, otherwise the accepted original |
| `citation_roles` | The references the validated diagnosis cited as supporting and conflicting; the only references the reasoner may cite |
| `human_validation` | `human_revised` and the reviewer's `revision_rationale` (or null). The reviewer identifier is never sent |

The strict response (`InterventionResponse`) has exactly nine required keys: `intervention_type` (`training`, `practice_simulation`, `coaching`, `process_correction`, `investigate_further`), `recommendation`, `rationale`, `target_change`, `fit_to_cause`, `evidence_reference_ids`, `limitations`, `missing_evidence`, and numeric `provider_reported_confidence` in `[0, 1]`. References must be copied from `citation_roles` without duplicates; `investigate_further` requires named missing evidence; extra keys (including statistics, IDs, provider metadata, or a generation mode) fail closed. The stored `InterventionProposal` also resolves the references to local `item_id`/`evaluation_id` pairs and carries locally stamped provider, model, region, generation mode, and timestamp.

The system prompt states that the human-validated diagnosis is authoritative and not to be re-diagnosed, defines the five types as considerations rather than rules, and says that frequency alone never justifies training, that an undetermined cause calls for investigation, that training an agent to work around a flawed process does not correct a process gap, and that the proposal is a recommendation a human reviews afterward.

## Solution Validator

`POST /interventions/diagnoses/{hypothesis_id}/validate-solution` is a logically separate stage with its own class, prompt, schema, and Converse call. It requires a stored proposal, rebuilds and re-verifies the same population and diagnosis, and sends the reasoner request plus `proposed_intervention` (the nine stored proposal fields). It answers only: does this proposed intervention logically address the human-validated cause and the observed problem? It may not propose a replacement diagnosis, cause, dimension, or intervention, and its output has no such fields.

The strict response (`SolutionResponse`) has exactly seven keys: `alignment_outcome` (`aligned`, `partially_aligned`, `misaligned`, `insufficient_evidence`), `alignment_assessment`, `aligned_points`, `misaligned_points`, `unsupported_assumptions`, `missing_information`, and numeric confidence. Outcomes must be grounded: `aligned` needs an aligned point with no misaligned point or unsupported assumption, `partially_aligned` needs an aligned point and a named concern, `misaligned` needs a misaligned point or an unsupported assumption, and `insufficient_evidence` needs missing information. Only `aligned` is recorded as `solution_validated`; the rest are `solution_questioned`. The prompt forbids equating a high failure rate with a training need, recurrence with a knowledge gap, diagnosis approval with training approval, or a supported diagnosis with a suitable intervention, and it does not penalize an investigate proposal for an undetermined cause.

Both adapters share the AWS-1/AWS-3 pattern: temperature 0, one user text block, only `stopReason: end_turn`, no repair, no coercion, no retry on semantic failure, no fixture fallback, sanitized fixed-message errors, and provenance stamped from the installed object. Defaults are `us-east-1` and `global.anthropic.claude-sonnet-4-6`; the global inference profile may route outside the client region. Live AWS was not used for implementation tests.

## Human validation and AWS-3 provenance

The reviewer's approved diagnosis is the only input. When the reviewer revised, the request carries the revision's cause, dimension, defect, explanation, citations, and rationale, and the superseded provider proposal is not sent. The AWS-3 semantic review is **not** a gate on human action and not an input to either AWS-4 call. It is recorded in the `InterventionRecord` as provenance: `evidence_review_status` is `evidence_validated`, `evidence_questioned`, `not_reviewed`, or `original_proposal_only` (the reviewer revised, so the stored review describes a different diagnosis), and `semantic_review` carries the validation ID, outcome, status, and whether it describes the validated diagnosis. The workspace can therefore say "Supervisor X approved this diagnosis with an evidence review status of Y."

## Records, idempotency, and audit

One process-local `InterventionRecord` per hypothesis holds the `validated_diagnosis` (the full `ApprovedDiagnosis`, including reviewer and approval time, kept locally), a digest of it, the evidence-review provenance, `status`, the immutable `proposal`, the immutable `solution_validation` (or null), the deterministic `handoff`, and timestamps. Repeated `propose` or `validate-solution` requests, including concurrent ones, return the stored record without another provider call; a failed or malformed provider turn stores nothing and may be retried. `GET /interventions/diagnoses/{hypothesis_id}` re-runs the approval gate and checks the digest on every read. Records disappear on process restart, like all diagnostic and design state; there is no database.

## M5 / AWS-5 handoff

`DesignHandoff` is the upstream decision AWS-5 consumes: `intervention_type`, the M5 `decision_type` it projects to (`training` and `practice_simulation` -> `training`; `coaching` and `process_correction` -> `non_training`; `investigate_further` -> `investigate`), `solution_status`, the IDs, `human_reviewed_intervention: false`, and `training_design_gate`:

| Gate | Meaning |
| --- | --- |
| `awaiting_solution_validation` | Training or practice proposed; no solution review yet |
| `permitted` | Training or practice proposed and the review found it `aligned`; M5 may run the training designer |
| `withheld` | Training or practice proposed but the review found it `partially_aligned`, `misaligned`, or `insufficient_evidence`; the training generator must not run |
| `not_applicable` | Coaching, process correction, or investigation; never reaches the training generator |

The gate is a lifecycle projection, not an approval. `ValidatedInterventionHandoff` implements the M5 `InterventionReasoner` protocol, so `DesignService` and `validate_decision` are unchanged: instead of asking a provider to decide, it reads the record and projects it onto `InterventionDecision`, which now carries optional `intervention_type`, `target_change`, `solution_alignment`, `intervention_id`, and `solution_validation_id` (null for pre-AWS-4 providers and fixtures; when present they must agree with `decision_type`). `POST /designs/diagnoses/{id}` returns 409 `intervention_not_proposed`, `solution_not_validated`, `training_design_withheld`, or `solution_questioned` until the preconditions hold. A questioned non-training proposal also stops before M5; aligned non-training and investigate decisions produce the usual `alternative_recommended` and `evidence_required` results with no training artifact. **AWS-5 should implement `TrainingDesigner.design(context, decision)` and read `decision.intervention_type` and `decision.target_change` first**; it is only invoked when the gate is `permitted`. The normal API, the real ResultsCX demo, and the synthetic M4 demo all install this handoff; the training designer stays unavailable outside the demo.

## Privacy boundary

The AWS-2 real ResultsCX boundary is reused exactly: both AWS-4 requests carry the saved structured-only projection, re-verified against a fresh `prepare_real_evidence` run, with no evaluator comment, minimized comment, answer, agent/evaluator/leader name, local evaluation or evidence ID, lineage, filename, sheet, path, or row, and no `diagnostic_text`. The reviewer identifier and approval time stay local. Diagnostic prose, missing-evidence entries, and the reviewer's revision rationale are screened with the AWS-3 identifier screen (known staff names as whole words, local ID patterns, lineage words, long verbatim comments) before any provider trip; a hit stops invocation and stores nothing. The reasoner's free-text proposal is screened with the same rule before storage or inclusion in the validator request. A remote AWS-4 call is only permitted when the diagnosis came through a bound synthetic or trusted ResultsCX Bedrock reasoner, mirroring AWS-3. This is a narrow screen, not PHI detection: a member name or health detail typed by a reviewer is not detected, and no anonymization or HIPAA claim is made.

## Review workspace

After human validation the workspace shows two new stages beneath the existing semantic evidence review and human validation panels, each visually distinct: **04 / Intervention proposed** (type, recommendation, rationale, target behavior or operational change, fit to cause, cited evidence opening the local rows, limitations, evidence still needed, reasoner-reported confidence with non-calibrated language, and the approval and evidence-review provenance sentence) and **05 / Solution validation** (outcome, validated or questioned status, assessment, what is and is not aligned, unsupported assumptions, missing information, validator-reported confidence, and the handoff gate in plain language). The M5 **Design Intervention** button appears only when the solution review found the proposal `aligned`. The command-center homepage is untouched.

## Demo and smoke

`scripts/run_m4_demo.py` installs fixed non-AI intervention and solution fixtures: resolution clarity proposes practice simulation (aligned, so the M5 training fixture may run); a missing workflow prompt proposes process correction (aligned, no training); all-pass follow-up proposes investigation (aligned, no training). `scripts/run_bedrock_synthetic_smoke.py` now records a synthetic approval after the AWS-3 review and runs both AWS-4 stages live, printing only counts, enums, confidence, gate, and status; `--skip-intervention` stops after AWS-3.

## Limits

Alignment outcomes are model judgments, not calibrated truth, and the reasoner and validator may run on the same model. No human approves the intervention in this milestone; the handoff says so. A questioned proposal needs correction and another review before M5, but this process-local prototype has no intervention revision workflow: a new proposal requires a new diagnosis lifecycle or a future explicit revision mechanism. Human-typed text reaches the provider after a narrow screen only. State is process-local.
