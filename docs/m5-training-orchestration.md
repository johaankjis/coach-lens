# M5 intervention and training orchestration

M5 extends the existing evidence graph: source QA criterion rows → deterministic M2 signal → M3 hypothesis → human-approved diagnosis → proposed intervention → target behavior → objective → activity → practice scenario → rubric criterion. The backend, not the browser, owns every transition after approval. A single `POST /designs/diagnoses/{hypothesis_id}` executes the downstream flow without additional prompts. `GET` on the same path reads the immutable aggregate result. The Next.js app proxies `/api/designs/*` to the local FastAPI service.

## Decision before design

The M3 `get_approved_diagnosis()` gate is mandatory. An arbitrary cause string cannot enter M5. The gate returns either the approved original diagnosis or the approved human revision; when revised, the superseded provider hypothesis is not passed to the design provider. M5 records the approval provenance in the result. It does not rediagnose or reinterpret QA scores.

`InterventionDecision` is an immutable, typed proposal: `training`, `non_training`, or `investigate`, with rationale, approved evidence citations, risks, unresolved questions, and proposed next actions. No cause-domain → intervention rule exists. The decision provider must explain its choice from the approved diagnosis. For `non_training`, the result contains recommended actions and no training artifact. For `investigate`, it must contain unresolved questions and likewise has no training artifact. Only `training` calls the training designer. These alternatives prevent a validated diagnosis from automatically becoming unnecessary training.

## Training and practice contracts

`TrainingDesign` contains the validated diagnosis reference, proposed performance context, observable target behaviors, measurable objectives, ordered sections, activities with instructions and success indicators, optional four-option decision checks with response-specific feedback, and at least one practice scenario. A scenario is a specification for later text or voice simulation, not a fixed transcript: synthetic persona context, tone, wants, withheld information, opening line, conversation beats with success/challenge guidance, completion criteria, debrief prompts, and an observable rubric. M5 does not run a simulation or score a learner.

Every target behavior references the approved diagnosis. Objectives reference target behaviors; activities and sections reference objectives; scenarios reference activities, objectives, and behaviors; each rubric criterion references a scenario behavior and an objective that itself references that behavior. Stable IDs begin with the run ID. Provider outputs are reduced to plain data and revalidated as fresh frozen objects. Deterministic checks reject duplicate or cross-run IDs, dangling references, inconsistent behavior/objective links, uncited intervention evidence, malformed branches, and bad decision-check structure. The result is snapshot-copied on reads. Provider objects cannot mutate the store.

The run ID is derived from the approved hypothesis ID and approval timestamp. A per-service async lock serializes creation. The first successful result is stored in process memory; subsequent POSTs return the exact stored snapshot rather than regenerating it. Failed provider output stores nothing and may be retried. Explicit regeneration and versioning are deferred. As with M3, process restarts discard state and multi-worker deployments do not share it.

## Provider and privacy boundary

`InterventionReasoner.decide(DesignInput)` and `TrainingDesigner.design(DesignInput, InterventionDecision)` are async replacement points. The normal API installs unavailable providers and returns 503; it does not silently claim to perform AI reasoning. `scripts/run_m4_demo.py` installs a controlled, fixed, non-AI M5 fixture alongside the M4 fixture. The result carries a service-assigned `generation_mode` so the UI identifies controlled demo output instead of calling it AI-generated. The synthetic resolution-clarity signal demonstrates training; the synthetic all-pass follow-up signal demonstrates investigation. To demonstrate a non-training branch in tests, the controlled fixture is configured for `non_training`. Future Bedrock adapters can implement these protocols without changing orchestration or domain contracts; M5 contains no AWS package, model selection, credentials, or configuration.

The design provider input contains the approved diagnosis, its already-validated citation IDs, aggregate signal criterion/counts, and human revision rationale when present. It does **not** include raw workbooks, source lineage, source identities, evaluator comments, or every QA row. The diagnosis text or reviewer rationale may nevertheless contain sensitive content entered upstream; this is data minimization, not anonymization or a HIPAA claim. Before using a remote provider with real records, review the M3 free-text privacy boundary. The local reviewer evidence API remains unauthenticated and may show sensitive comments and lineage. No production auth or persistence is provided.

## Status and handoff

Training results are labeled `ready_for_alignment_review`, never validated training. Non-training results are `alternative_recommended`; investigate results are `evidence_required`. M6 should independently audit whether proposed behaviors, objectives, activities, practice, and rubric truly align to the validated diagnosis and evidence. M5 structural validation proves reference integrity, not pedagogical quality or causal truth.

**M5 does:** validated diagnosis → intervention decision → training outline → proposed activities → hands-on practice scripting → Ready for Alignment Review, when training is selected.

**M5 does not:** change QA scoring, rediagnose, bypass approval, validate generated training, perform Alignment Guard review, simulate or score a learner, implement voice, integrate AWS/Bedrock, calculate ROI, claim HIPAA compliance, or provide production auth/persistence. It does not import full ResultsCX TSO spreadsheets. The fixture is synthetic and non-AI.
