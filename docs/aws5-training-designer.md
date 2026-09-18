# AWS-5: ResultsCX Training Designer and hands-on practice generation

AWS-5 proposes a training package for a validated training intervention inside the existing M5 design run: outline, activities, decision-based knowledge check, scripted practice simulation with a member persona, and scoring rubric, in one `POST /designs/diagnoses/{hypothesis_id}` call. It does not diagnose, decide the intervention, validate the solution, or judge alignment. Those remain M3/M4 (diagnosis and human validation), AWS-4 (intervention reasoning and solution validation), and AWS-6 (alignment check).

## Flow

```
human-validated diagnosis (M3/M4 gate)
  -> intervention decision (M5 fixture today; AWS-4 reasoner + solution validator later)
  -> ValidatedTrainingIntervention              app/design/intervention_input.py
  -> ResultsCX design guidance (versioned)      app/design/guidance.py
  -> Bedrock Training Designer (Converse)       app/design/bedrock.py
  -> strict designer contract, no repair        DesignerResponse + parse_designer_response
  -> run-prefixed M5 TrainingDesign             to_training_design
  -> M5 structural validation                   app/design/validation.py
  -> DesignResult + AlignmentTrace              app/design/alignment.py, service.py
  -> ready_for_alignment_review (AWS-6 handoff)
```

Nothing after the gate asks the user for another prompt. A refused, malformed, or blocked run stores nothing and may be retried; a stored run is immutable and returned as a snapshot, as in M5.

## Input boundary for AWS-4

`ValidatedTrainingIntervention` is the only thing the designer designs from. It carries the run and diagnosis identifiers, the confirmed gap copied from the approved diagnosis (observed behavior, cause domain, explanation, performance dimension, whether a human revised it), the intervention summary and evidence references, a `training_focus` (`knowledge`, `skill`, or `knowledge_and_skill`), optional supplied `operational_context`, and a `validation_source` of `m5_intervention_decision` or `aws4_solution_validator`. Its contract refuses any cause other than `knowledge_gap` or `skill_gap`.

Today `training_intervention_from_decision()` adapts the existing M5 `InterventionDecision` plus the approved diagnosis into that model. The adapter refuses, with a fixed reason and no provider call:

| Situation | Reason | Client response |
| --- | --- | --- |
| `non_training` decision | `not_training_intervention` | 422 `training_design_refused` |
| `investigate` decision | `investigation_required` | 422 |
| training decision, `undetermined` cause | `root_cause_unconfirmed` | 422 |
| training decision, `process_gap` cause | `process_gap_not_training` | 422 |
| decision from another run or diagnosis | `intervention_mismatch` | 422 |

The M5 service never calls the designer for `non_training` or `investigate`; the designer refuses them anyway so a direct caller gets the same answer. Refusal messages come from a fixed table in `service.py`; a refusal with a reason outside that table is reported as a generic provider failure so no provider text reaches a client. The cause-to-focus mapping in the adapter is provisional. The M5 controlled fixture remains available for the synthetic demo. The demo no longer couples that fixture intervention to a provider-backed training run.

**AWS-4 integration is still required.** The independently implemented AWS-4 branch (`2406219`) adds `InterventionDecision.intervention_type`, `target_change`, `solution_alignment`, `intervention_id`, and `solution_validation_id`, plus a stored `DesignHandoff.training_design_gate`. Its `ValidatedInterventionHandoff` checks that a solution review exists and that training was not withheld before projecting the decision. At integration, install that handoff as the only intervention source for provider-backed design in the normal API and real demo; do not retain a fixture-intervention/provider-designer combination as an application route. Adapt `training_intervention_from_decision` to accept only `training` or `practice_simulation` with the stored permitted gate and solution review ID, use `target_change` and the proposal recommendation instead of deriving the training summary from `rationale`, and set `validation_source="aws4_solution_validator"`. Map training focus from the intervention type and approved cause without treating cause as a new intervention decision. Preserve the non-training and investigate M5 branches. The current standalone smoke script is an explicit synthetic provider harness, not a validated AWS-4 application workflow; replace its fixture decision with the AWS-4 handoff when integrating.

## ResultsCX methodology integration

`app/design/guidance.py` is compact, versioned local design guidance (`resultscx-design-guidance/2`) consistent with the repository's M3 and M5 principles: needs analysis is diagnostic; AI findings are hypotheses until a human validates them; the confirmed cause precedes design; target behaviors are observable; objectives and assessments have measurable standards; knowledge checks ask for decisions with four options and specific feedback; and the rubric defines scorable practice behavior. Its design chain is the structural M5 chain from approved diagnosis through intervention, behavior, objective, activity, practice, and rubric. The repository does not contain the claimed named ResultsCX template sequence or a source template workbook, so the guidance does not assert one. The version is recorded on every provider-generated design.

Three kinds of content are kept apart: methodology (guidance module, system prompt), real QA evidence (never sent; see the privacy boundary), and generated training content (the designer response, stored as an M5 `TrainingDesign` labeled a proposal).

## Bedrock invocation and contract

`BedrockTrainingDesigner` implements the M5 `TrainingDesigner` protocol with the AWS-1/AWS-3 pattern: Bedrock Runtime `Converse`, one system prompt, one user text block, temperature `0`, `maxTokens` `8000`, explicit connect/read timeouts, standard retries, `us-east-1` and `global.anthropic.claude-sonnet-4-6` by default, following `COACHLENS_BEDROCK_REGION` and `COACHLENS_BEDROCK_MODEL_ID`. The global inference profile may route outside the client region.

The user message is one JSON object with exactly these keys: `design_guidance_version`; `confirmed_performance_gap` (`reference` `GAP-001`, `qa_criterion`, `observed_behavior`, `confirmed_cause_domain`, `performance_dimension`, `cause_explanation`, `human_revised`); `validated_intervention` (`reference` `INT-001`, `training_focus`, `summary`); and `supplied_operational_context` (a list of operational facts, empty when none were supplied). No counts, rates, scores, evidence rows, references, local IDs, or run IDs travel.

The system prompt has three parts: the designer instructions, the guidance text, and `response_contract()`, rendered from the `DesignerResponse` JSON schema so every key, nesting level, type, and bound in the prompt is the one the parser enforces. The response uses short local labels (`B1`, `O1`, `K1_OPT1`, `BEAT1`, `R1`, `M1`) that the adapter prefixes with the run ID; the model never sees or emits run, diagnosis, provider, generation-mode, or timestamp fields, and any such key is refused as an extra key.

Fail-closed rules before M5 validation: JSON must parse to one object without duplicate keys; only `stopReason: end_turn` is accepted; every key is required and no extras are allowed; primitive types are not coerced; text is non-blank and bounded; identifiers are unique across the package; every target behavior cites `GAP-001`; every focus needs at least one knowledge check and a practice scenario with at least two scripted turns; each knowledge check has exactly four options with one correct; any percentage anywhere, or an "N of M calls/evaluations" statement in the performance context, is refused because the designer was given no statistics; placeholder tokens must match their declared detail IDs and be used in the design; escalation handling is refused when no operational context was supplied. There is no repair, semantic retry, or fixture fallback. Provider metadata (Amazon Bedrock, model, region, request ID, UTC time) is stamped locally; `generation_mode` is assigned by the service from the installed objects.

## Output contract

The result is the existing M5 `TrainingDesign` with optional additions, so the controlled fixture and the frontend guard stay valid:

- `design_basis`: `gap` (diagnosis and signal IDs, observed behavior, cause, dimension, human-revised flag), `intervention` (run ID, `training`, focus, validation source, summary), `guidance_version`, `supplied_operational_context`. Built locally from the validated input; M5 validation rejects a basis that disagrees with the approved diagnosis.
- `objectives[].condition`, `.observable_action`, `.standard`: the decomposition that makes an objective observable and measurable. Required from the provider, optional on the model.
- `decision_checks[].behavior_ids`: direct trace to behaviors, which must be reachable through the check's objectives.
- `practice_scenarios[].scenario_setup`, `.escalation_expectation` (`null` unless escalation handling was supplied), and per-turn `beats[].expected_learner_behavior`, `.facilitator_cue`, `.behavior_ids`.
- `missing_operational_details[]`: `detail_id`, `placeholder`, `description`, `needed_for`. Every `[PLACEHOLDER:…]` token anywhere in a design must be declared here; undeclared tokens are refused. This is how absent policies, contacts, timings, or procedures are surfaced rather than invented.

M5 structural validation also now requires that each knowledge-check option's feedback is distinct and does not merely repeat the option, and that turn and check behavior references stay inside the scenario or objective they belong to. These apply to every training design, fixture included.

## Alignment handoff for AWS-6

`DesignResult.alignment_trace` is built by the service from the validated design, never from the provider. It enumerates every gap → intervention → target behavior → objective → activity → practice scenario → rubric criterion path (one link per rubric criterion), every knowledge check → objective → behaviors link, and the missing-detail IDs. Its `assessment` is always `structural_references_only`: the trace proves the references exist and are consistent, and says nothing about whether the content is pedagogically aligned. AWS-6 can walk the trace mechanically and read the referenced text for a semantic judgement. The status stays `ready_for_alignment_review`, and the serialized result never contains the words aligned, validated training, or approved training.

## Privacy boundary (AWS-2 preserved)

The designer sends no evaluator comment, name, local ID, evaluation ID, evidence reference, source lineage, path, filename, sheet, row, raw workbook, count, or rate. The request is an explicit allowlist; tests assert its keys and that known synthetic names, comments, IDs, and lineage never appear. Row-level evidence is not needed to design training, so none is sent.

The free text that does travel (observed behavior, explanation, intervention summary, supplied operational context) was typed by a provider or a reviewer upstream. Before invocation the designer requires a bound `DiagnosticService` whose reasoner declares `local_fixture`, `synthetic_only`, or `real_minimized`; a `privacy_blocked`, `undeclared`, or unavailable reasoner, or no bound service, blocks with `design_privacy_blocked` before any client exists. It then screens that text with the AWS-3 local screen against known agent, evaluator, and leader names, local identifiers, filenames, sheets, and verbatim comments, and blocks on a hit. This is a narrow boundary, not a PHI detector; the M5 note that free text needs a reviewed minimization step before real remote use still applies.

## Wiring and demo

With `COACHLENS_BEDROCK_ENABLED=false` (default) nothing changes. With it `true`, `app.main` and the real ResultsCX demo installer put a `BedrockTrainingDesigner` in the design service beside an unavailable intervention provider, so `/diagnostics/mode` reports `design_provider: provider` while a design run still stops at 503 until AWS-4 installs a reasoner. `scripts/run_m4_demo.py` always uses the controlled M5 fixture for its application workflow. `scripts/run_bedrock_training_smoke.py` invokes the designer once with synthetic fixtures as an isolated provider smoke test and prints counts only. Live AWS was not used for the review.

The review workspace shows the design basis, the missing operational details, objective standards, scenario setup, escalation handling, and per-turn expected behavior and facilitator cues when present, and renders the fixture unchanged otherwise.

## Limits

The designer's output quality depends on the model; the contract enforces structure, traceability, measurability fields, and the no-statistics and no-invention rules, not pedagogical soundness. The cause-to-focus adapter is a placeholder for AWS-4's validated intervention. No simulation is run and no learner is scored. Results live in process memory. Bedrock native structured outputs are not used, for the reasons recorded in the AWS-1 guide.
