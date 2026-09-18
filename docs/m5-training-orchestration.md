# M5 intervention and training orchestration

AWS-5 adds a provider-backed training designer, optional design-basis and scripted-practice fields, and a service-built alignment trace on top of these contracts; see [the AWS-5 guide](aws5-training-designer.md). Everything below still holds.

M5 extends the existing evidence graph: source QA criterion rows → deterministic M2 signal → M3 hypothesis → human-approved diagnosis → proposed intervention → target behavior → objective → activity → practice scenario → rubric criterion. The backend, not the browser, owns every transition after approval. A single `POST /designs/diagnoses/{hypothesis_id}` executes the downstream flow without additional prompts. `GET` on the same path reads the immutable aggregate result. The Next.js app proxies `/api/designs/*` to the local FastAPI service.

## Decision before design

The M3 `get_approved_diagnosis()` gate is mandatory. An arbitrary cause string cannot enter M5. The gate returns either the approved original diagnosis or the approved human revision; when revised, the superseded provider hypothesis is not passed to the design provider. M5 records the approval provenance in the result. It does not rediagnose or reinterpret QA scores.

`InterventionDecision` is an immutable, typed proposal: `training`, `non_training`, or `investigate`, with rationale, approved evidence citations, risks, unresolved questions, proposed next actions, and the provider's self-reported `provider_metadata` (provider and model) for audit. It is AI- or fixture-proposed and is **not** human validated; the only human decision in the chain is the M3 diagnosis approval. No cause-domain → intervention rule exists. The decision provider must explain its choice from the approved diagnosis. For `non_training`, the result contains recommended actions and no training artifact. For `investigate`, it must contain unresolved questions and likewise has no training artifact. Only `training` calls the training designer. These alternatives prevent a validated diagnosis from automatically becoming unnecessary training.

## Training and practice contracts

`TrainingDesign` contains the validated diagnosis reference, proposed performance context, observable target behaviors, measurable objectives, ordered sections, activities with instructions and success indicators, optional four-option decision checks with response-specific feedback, and at least one practice scenario. A scenario is a specification for later text or voice simulation, not a fixed transcript: synthetic persona context, tone, wants, withheld information, opening line, conversation beats with success/challenge guidance, completion criteria, debrief prompts, and an observable rubric. M5 does not run a simulation or score a learner.

Every target behavior references the approved diagnosis. Objectives reference target behaviors; activities and sections reference objectives; scenarios reference activities, objectives, and behaviors; each rubric criterion references a scenario behavior and an objective that itself references that behavior. Stable IDs begin with the run ID. Provider outputs are reduced to plain data **recursively** (nested pre-built model instances inside a mapping are dumped and re-validated too) and revalidated as fresh frozen objects, so no provider-owned object is ever stored. Deterministic checks reject duplicate or cross-run IDs, dangling references, inconsistent behavior/objective links, uncited intervention evidence, malformed branches, bad decision-check structure (exactly four distinct options, exactly one correct), and coverage gaps: every objective has an activity, every activity appears in the outline, every target behavior has an objective, is exercised by at least one practice scenario, and every behavior a scenario claims to exercise has a rubric criterion. Lists are bounded at 200 entries and text at 20,000 characters as storage-safety limits. `TrainingDesign` also carries `provider_metadata`. The result is snapshot-copied on reads. Provider objects cannot mutate the store.

These checks are reference integrity and coverage only. A plan whose behaviors, objectives, activities, and rubric are all well-formed and mutually consistent but that addresses the wrong problem (for example, an empathy role-play for a documentation-accuracy diagnosis) passes M5 validation and is stored as `ready_for_alignment_review`. M5 never labels a design aligned, validated, or approved; that judgement is M6's.

The run ID is derived from the approved hypothesis ID and approval timestamp. A per-service async lock serializes creation. The first successful result is stored in process memory; subsequent POSTs return the exact stored snapshot rather than regenerating it. Failed provider output stores nothing and may be retried. Explicit regeneration and versioning are deferred. As with M3, process restarts discard state and multi-worker deployments do not share it.

## Provider and privacy boundary

`InterventionReasoner.decide(DesignInput)` and `TrainingDesigner.design(DesignInput, InterventionDecision)` are async replacement points. The normal API installs unavailable providers and returns 503; it does not silently claim to perform AI reasoning. Only the service's own `design_provider_unavailable` error passes through; any other exception a provider raises, including a `DesignError` it constructs itself, becomes a generic `design_provider_failure` (502) so provider text never reaches a client. `scripts/run_m4_demo.py` installs a controlled, fixed, non-AI M5 fixture alongside the M4 fixture. The result carries a service-assigned `generation_mode` so the UI identifies controlled demo output instead of calling it AI-generated. The synthetic resolution-clarity signal demonstrates training; the synthetic all-pass follow-up signal demonstrates investigation. To demonstrate a non-training branch in tests, the controlled fixture is configured for `non_training`. Future Bedrock adapters can implement these protocols without changing orchestration or domain contracts; M5 contains no AWS package, model selection, credentials, or configuration.

### Exact provider input (review before any remote adapter)

Both providers receive a fresh `DesignInput.provider_view()` copy per call with exactly these fields:

| Field | Origin | Notes |
| --- | --- | --- |
| `run_id` | M5 service | Derived hash |
| `approved.hypothesis_id`, `approved.signal_id` | M3 | Opaque IDs |
| `approved.diagnosis.observed_behavioral_defect`, `.explanation` | M3 provider or M4 reviewer | **Free text**, verbatim |
| `approved.diagnosis.cause_domain`, `.performance_dimension` | M3/M4 | Enums |
| `approved.diagnosis.supporting_evidence`, `.conflicting_evidence` | M3 | `{item_id, evaluation_id}` references only; `evaluation_id` is the M2 pseudonymous internal ID |
| `approved.diagnosis.missing_evidence` | M3 provider or M4 reviewer | **Free text**, verbatim |
| `approved.diagnosis.provider_reported_confidence`, `.provider_metadata` | M3 | Only when the original hypothesis (not a revision) was approved |
| `approved.approved_by` | — | Replaced by `[reviewer]`; the reviewer identifier is not sent |
| `approved.approved_at`, `approved.human_revised` | M3 | Timestamp and flag |
| `signal_criterion` | M2 | QA question wording |
| `signal_fail_count`, `signal_evaluated_results` | M2 | Aggregate counts |
| `allowed_evidence` | M3 | Same references as above, flattened |
| `revision_rationale` | M4 reviewer | **Free text**, verbatim, when a revision was approved |

It does **not** include raw workbooks, source filename/sheet/row lineage, agent/evaluator/leader names, evaluator feedback, scores, or any QA row. The free-text fields above are typed by a provider or a human upstream and could contain member or employee names, health details, or account identifiers if someone entered them; M5 applies no redaction to them. This is data minimization, not anonymization, de-identification, or a HIPAA claim. Before a Bedrock or other remote adapter receives these fields from real records, that free text needs a separately reviewed minimization or redaction step, alongside the M3 free-text privacy boundary. The local reviewer evidence API remains unauthenticated and may show sensitive comments and lineage. No production auth or persistence is provided.

## Status and handoff

Training results are labeled `ready_for_alignment_review`, never validated training. Non-training results are `alternative_recommended`; investigate results are `evidence_required`, and neither carries a training artifact or the alignment-review state. The UI labels every M5 artifact as a proposal, names the origin (controlled fixture or AI provider, from the service-assigned `generation_mode` plus the provider's metadata), and states that alignment review has not run. M6 should independently audit whether proposed behaviors, objectives, activities, practice, and rubric truly align to the validated diagnosis and evidence. M5 structural validation proves reference integrity, not pedagogical quality or causal truth.

**M5 does:** validated diagnosis → intervention decision → training outline → proposed activities → hands-on practice scripting → Ready for Alignment Review, when training is selected.

**M5 does not:** change QA scoring, rediagnose, bypass approval, validate generated training, perform Alignment Guard review, simulate or score a learner, implement voice, integrate AWS/Bedrock, calculate ROI, claim HIPAA compliance, or provide production auth/persistence. It does not import full ResultsCX TSO spreadsheets. The fixture is synthetic and non-AI.
