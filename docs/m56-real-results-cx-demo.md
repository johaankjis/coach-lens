# M5.6 local ResultsCX demo path

AWS-2 extends this demo with an optional structured-only Bedrock diagnostic path when enabled; evaluator comments stay local. See [AWS-2 real evidence boundary](aws2-real-evidence-boundary.md). The original no-provider mode remains the default.

Place these three confidential files directly in ignored `data/raw/`, keeping the filenames exactly as shown:

- `Call Flow - Business Process (Healthcare Partner).xlsx`
- `Compliance Raw Data (Healthcare Partner).xlsx`
- `QA Raw Data - Member Experience Focus (Healthcare Partner).xlsx`

From the repository root, after installing the API dependencies, start the real-data backend:

```bash
services/api/.venv/bin/python scripts/run_results_cx_demo.py
npm --prefix apps/web run dev
```

Open <http://localhost:3000>. The backend binds to `127.0.0.1:8000`. Its startup banner says `REAL RESULTS CX`; `GET /diagnostics/mode` returns `mode: real_results_cx` with `diagnostic_provider: unavailable`, `remote_diagnosis: unavailable`, and `design_provider: unavailable`, plus `evaluation_count` and `signal_count` (with `COACHLENS_BEDROCK_ENABLED=true` the first two become `provider` and `privacy_blocked`; see the AWS-1 guide). `mode` is the label the startup script declared; the provider fields and counts are read from the services actually installed in the process, so the label cannot claim a provider or fixture that is not there. Missing, extra (including nested or differently cased copies), misclassified, or invalid workbooks stop startup with a validation error that names the offending file. There is no fallback to synthetic records. The normal API startup does not require these files.

The loader checks the exact filenames, then calls the existing M2 workbook discovery and normalization in memory. It does not write `data/processed` output. M2 owns source Yes/No and pass-marker consistency, evaluation IDs, criterion records, incomplete criterion coverage, and workbook/sheet/row lineage. M3 reuses M2 `analyze` to create **every** observed domain/criterion signal, including zero-failure criteria. Each signal counts actual criterion rows and represented evaluations, pass/fail results, feedback-bearing rows, and scores. The display order is descending failure count, then failure rate, then domain and criterion; this is an ordering policy, not a problem threshold. A criterion missing for some evaluations has a smaller represented-evaluation count. Every signal carries both `evaluated_evaluations` (evaluations that contain the criterion) and `total_evaluations` (evaluations loaded), and the workspace shows "N of T loaded evaluations contain this criterion", so a rate over a partially covered criterion is not read as dataset-wide prevalence; the workflow makes no claim about a required per-call criterion count. Selecting a signal opens the exact normalized criterion rows and source lineage through the existing reviewer evidence route.

This mode has **no diagnostic or design provider**. Requesting a diagnosis returns `reasoner_unavailable` (HTTP 503); no hypothesis is fabricated from failure rates, and no M5 design can begin without a human-approved diagnosis. The existing approval/revision and M5 design contracts remain unchanged for a future provider. For a complete controlled workflow demonstration, run `scripts/run_m4_demo.py` separately: it uses only synthetic QA records and fixed non-AI diagnostic/design fixtures. Its `/diagnostics/mode` response is `synthetic_demo`. The ordinary API mode is `unconfigured` or `local_normalized`, depending on its configuration.

Reviewer evidence contains raw evaluator feedback and source locations and must stay on a trusted local machine. The provider-view route omits lineage and redacts exact known structured names in feedback, but this is **not** general PII/PHI removal. Do not expose the unauthenticated API or web proxy publicly, or send real feedback to a remote provider. A separate privacy review is required before Bedrock integration. M5.6 does not implement Bedrock, AWS configuration, new reasoning, alignment, voice, ROI, deployment, auth, or persistence. Service state disappears on restart.
