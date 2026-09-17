# M4 Review Workspace

## Purpose and ownership

The workspace gives QA supervisors and L&D reviewers one place to inspect deterministic QA signals, challenge a diagnostic hypothesis, and record a human decision. It has three visible levels:

1. **Observed:** `PerformanceSignal` counts, denominators, and rates come from M2 validated ResultsCX QA records through M3. Source QA answers, scores, and pass markers retain M2 meaning. M4 does not reinterpret Yes/No, question wording, or evaluator intent.
2. **Proposed:** An M3 reasoner returns a typed diagnostic hypothesis with cause, performance dimension, explanation, citations, missing evidence, and provider-reported confidence. The backend validates it before storage. Until approval, the UI says it is a hypothesis awaiting human validation. The local demo fixture is explicitly labeled as non-AI.
3. **Validated:** Only an M3 approval response lets the UI show Human Validated and Ready for Design. Approval means a reviewer accepted a diagnosis for this workflow; it does not prove causal truth.

The active signal drives the central review and evidence inspector. Existing hypotheses can be selected from review history. The structured lineage runs source criterion rows → observed signal → hypothesis → human decision. A citation opens its exact criterion row, source answer/result, score, feedback, evaluation reference, and workbook/sheet/row. The special `signal` citation represents an aggregate and has no evaluation ID. Supporting and conflicting citations have equal visual prominence. M3 `missing_evidence` is shown verbatim; the UI does not invent limitations.

## Review workflow

1. Select a QA signal. Its failure count/rate and feedback count remain labeled observed.
2. Inspect source evidence. If there is no hypothesis, request one through `POST /diagnostics/signals/{id}/hypotheses`.
3. Inspect explanation, supporting and conflicting citations, and missing questions. The provider's exact confidence value is labeled **model-reported confidence** and explicitly identified as a self-report, not a calibrated probability. No threshold or probability interpretation is added.
4. Enter a reviewer identifier. Approve, reject with rationale, or revise with rationale and a typed correction. Revision allows changing the cause, performance dimension, defect description, explanation, citation relationships, and missing evidence. The original proposal remains visible and in M3 audit history. A revised diagnosis requires a separate approval.
5. The UI uses the returned `DiagnosticRecord` from each mutation, after a runtime shape check of status, hypothesis, citations, and events; a payload that fails the check is reported as an unexpected response rather than rendered. A failed operation never fabricates success. A 409 conflict reloads the record. Rejected diagnoses are never Ready for Design. Once a record carries a human revision, the original proposal card is labelled revised/superseded and never Human Validated; only the revision section and the validation panel show approval, naming the accepted cause and dimension. Overlapping clicks are ignored while a request is in flight, and a hypothesis created for a signal the reviewer has since left is not shown under another signal. Approval displays available reviewer and timestamp metadata.

The UI handles empty signals, absent hypotheses, loading, unavailable evidence/backend/provider, invalid provider output, failed mutations, rejected/revised/approved records, and evidence rows without feedback. API error messages are mapped to safe user text instead of displaying internal details.

## Small API additions

M3 remains the source of truth. `GET /diagnostics/signals/{id}/hypotheses` lists deep-copied records for a known signal, newest first, so history survives navigation within the process. `GET /diagnostics/signals/{id}/review-evidence` exposes the internal `EvidenceBundle` to the **local reviewer** with source lineage. The existing `/evidence` route continues returning the minimized provider view without lineage. No citation, provider, approval, lock, or immutability contract was relaxed. The web app proxies only `/api/diagnostics/*` through Next.js to `<origin>/diagnostics/*` for same-origin browser access; no other backend path is reachable through the proxy. `COACHLENS_API_ORIGIN` is read by `next.config.ts` when `next dev` starts or when `next build` runs (rewrites are compiled into the production build), never from the browser; it must be a bare origin such as `http://127.0.0.1:8000` with no trailing slash. Because the proxy forwards the reviewer evidence route, whatever the web server is bound to can read feedback and workbook lineage; the dev and start scripts bind to `127.0.0.1` for that reason.

## Privacy and deployment limits

Reviewer evidence includes evaluator feedback and source workbook locations. M3 removes structured names and workbook locations from the provider-facing view and replaces whole-word matches for known structured names in feedback, but it does not remove other identifying or health information in free text. The boundary is **identity-minimized, not anonymized**. Do not expose the current unauthenticated reviewer API to untrusted clients or connect real feedback to a remote provider without a separate privacy review. Reviewer IDs are unauthenticated strings. Diagnostic state is process-local and disappears on restart; multi-worker deployments do not share it.

## Local development/demo

Install backend dependencies into `services/api/.venv` and frontend dependencies with `npm ci --prefix apps/web`. From the repository root:

```bash
PYTHONPATH=services/api services/api/.venv/bin/python scripts/run_m4_demo.py
npm --prefix apps/web run dev
```

Open <http://localhost:3000>. The demo script installs four **synthetic** evaluations and a `DemoFixtureReasoner` only for that process. Its text and `0.78` confidence are fixed fixture values, not AI inference or calibrated probability. IDs for citations are taken from the actual M3 bundle, and M3 validates every fixture response. Approval/rejection/revision use the real M3 service and are lost when the demo process exits. Do not use this script with real ResultsCX data. The normal FastAPI startup has no reasoner and returns 503 for diagnosis requests; it may load ignored M2 JSONL for signal and evidence review as documented in the M3 guide.

## Boundaries

**M4 does:** QA signals → evidence → diagnostic hypothesis → human validation → validated diagnosis.

**M4 does not:** independently determine source QA scoring semantics; reinterpret ResultsCX Yes/No answers; generate training, intervention choices, simulations, or voice practice; integrate AWS or Bedrock; claim provider confidence is probability; or claim AI hypotheses are facts. Ready for Design is the terminal M4 state, not a training action.
