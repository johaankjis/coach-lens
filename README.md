# CoachLens AI

CoachLens AI is an evidence-driven performance diagnosis and training platform for the ResultsCX x AWS AI competition. Its planned workflow connects QA evidence to quantitative analysis, human-validated diagnosis, selected interventions, practice, and outcome measurement. Milestone 5 extends the review workspace from Ready for Design through a proposed intervention and, when appropriate, a training outline, activities, and practice specification. Training stops at Ready for Alignment Review. AWS-1 adds a synthetic-only Amazon Bedrock diagnostic adapter; see [the AWS-1 guide](docs/aws1-bedrock-diagnostics.md) for its privacy boundary and smoke procedure. AWS-3 adds [independent semantic evidence review](docs/aws3-semantic-evidence-validator.md) before the human decision.

## Repository structure

| Path | Purpose |
| --- | --- |
| `apps/web` | Next.js product shell: Home command center and the Agent Insights review workspace |
| `services/api` | FastAPI service with health and diagnostic endpoints |
| `packages/contracts` | Reserved for future shared contracts |
| `data/raw` | Local supplied datasets; Git ignores everything under `data/` except the `.gitkeep` markers |
| `data/processed` | Local normalized JSONL; Git-ignored |
| `docs` | Product and architecture notes |
| `scripts` | Local ResultsCX profiling and normalization CLIs |

## Prerequisites

- Node.js 22.12 or newer and npm (required by frontend test tooling)
- Python 3.11 or newer

## Frontend

```bash
cd apps/web
npm ci
npm run dev
```

Open <http://localhost:3000>. For a production run, use `npm run build` followed by `npm run start`.

## Backend

```bash
cd services/api
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env  # optional local configuration
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/health>. Environment variables prefixed `COACHLENS_API_` configure the service; see `services/api/.env.example`. The `.env` file is optional and ignored by Git.

## Checks

```bash
(cd services/api && python -m pytest)
npm ci --prefix apps/web
npm --prefix apps/web run lint
npm --prefix apps/web run typecheck
npm --prefix apps/web run test
npm --prefix apps/web run build
```

Never commit supplied ResultsCX healthcare QA datasets. Keep them under `data/raw`. Git ignores everything under `data/` (including files placed directly in `data/`) except the `.gitkeep` directory markers, so derived files under `data/processed` are ignored too. Do not use `git add -f` on these directories or commit credentials in `.env` files.

## ResultsCX data foundation

After installing the backend dependencies, keep the three supplied `.xlsx` workbooks under ignored `data/raw`. From the repository root:

```bash
services/api/.venv/bin/python scripts/profile_results_cx_data.py --input data/raw
services/api/.venv/bin/python scripts/normalize_results_cx_data.py --input data/raw --output data/processed
```

Profiling prints aggregates only. Normalization writes confidential row-level JSONL to ignored `data/processed/evaluations.jsonl` and prints domain totals. See [the M2 data guide](docs/results-cx-data-foundation.md) for schema, identity, lineage, analytics definitions, and limits.

See [product spec](docs/product-spec.md) and [architecture](docs/architecture.md) for the intended later system.

## UI-1 Home / Command Center

The frontend opens on a Home command center (`/`) that summarizes observed QA gaps, the priority insight under review, its AWS-3 evidence review and human-validation status, and typed pending slots for later intervention, training, alignment, and outcome milestones. Its **Review Evidence & Validate** action routes into the unchanged review workspace at `/agent-insights?signal=<id>` (Agent Insights). Training, Role-Play, KPI Tracker, Reports, and Resources are planned pages with no controls or figures. Home computes no QA statistics; see [the UI-1 guide](docs/ui1-command-center.md) for the read-model and wiring points.

## M5 design flow and M4 review workspace

The frontend runs at <http://localhost:3000> and proxies `/api/diagnostics/*` and `/api/designs/*` to the local FastAPI service at `http://127.0.0.1:8000` (override with `COACHLENS_API_ORIGIN`). For a safe end-to-end demo using **synthetic** QA records and **fixed non-AI fixtures**, run `PYTHONPATH=services/api services/api/.venv/bin/python scripts/run_m4_demo.py` from the repository root, then `npm --prefix apps/web run dev`. Approve a diagnosis, then select **Design Intervention**. The resolution-clarity signal demonstrates training; the all-pass follow-up signal demonstrates the investigate branch. Demo outputs pass real validation. See [the M5 guide](docs/m5-training-orchestration.md) and [the M4 guide](docs/m4-review-workspace.md).

## M3 diagnostic engine

The diagnostic API starts with no local QA records. To use ignored M2 output, set `COACHLENS_API_DIAGNOSTIC_EVALUATIONS_PATH=data/processed/evaluations.jsonl` before starting Uvicorn from the repo root. Signal and evidence routes then work; the evidence view minimizes identity but is not anonymized (see the guide's privacy boundary). Diagnosis creation returns 503 until a reasoning provider is injected; the included controlled test reasoner is for tests only. Reviews are held in process memory and disappear on restart. See [the M3 diagnostic guide](docs/m3-diagnostic-engine.md) for semantics, routes, privacy, the review gate, and the future Bedrock adapter point.

## M5.6 real ResultsCX demo

For an explicit, local-only real-workbook review path, place the three supplied files in `data/raw/` and run `services/api/.venv/bin/python scripts/run_results_cx_demo.py` from the repository root, then start the frontend. This mode uses M2 normalization and M3 observed signals/evidence, but has no diagnostic provider; diagnosis requests return 503 and cannot proceed to M5 design. It never falls back to synthetic data. Use the separate `run_m4_demo.py` for the controlled synthetic end-to-end workflow. The backend startup banner and `/diagnostics/mode` identify the running mode. See [the M5.6 guide](docs/m56-real-results-cx-demo.md) for exact filenames and privacy limits.
