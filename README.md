# CoachLens AI

CoachLens AI is an evidence-driven performance diagnosis and training platform for the ResultsCX x AWS AI competition. Its planned workflow connects QA evidence to quantitative analysis, human-validated diagnosis, selected interventions, practice, and outcome measurement. Milestone 3 adds deterministic QA signals, evidence bundles, typed diagnostic hypotheses, and human review. It stops before training design.

## Repository structure

| Path | Purpose |
| --- | --- |
| `apps/web` | Minimal Next.js frontend shell |
| `services/api` | FastAPI service with health and M3 diagnostic endpoints |
| `packages/contracts` | Reserved for future shared contracts |
| `data/raw` | Local supplied datasets; Git ignores everything under `data/` except the `.gitkeep` markers |
| `data/processed` | Local normalized JSONL; Git-ignored |
| `docs` | Product and architecture notes |
| `scripts` | Local ResultsCX profiling and normalization CLIs |

## Prerequisites

- Node.js 20.9 or newer and npm
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

## M3 diagnostic engine

The diagnostic API starts with no local QA records. To use ignored M2 output, set `COACHLENS_API_DIAGNOSTIC_EVALUATIONS_PATH=data/processed/evaluations.jsonl` before starting Uvicorn from the repo root. Signal and provider-safe evidence routes then work. Diagnosis creation returns 503 until a reasoning provider is injected; the included controlled test reasoner is for tests only. Reviews are held in process memory and disappear on restart. See [the M3 diagnostic guide](docs/m3-diagnostic-engine.md) for semantics, routes, privacy, the review gate, and the future Bedrock adapter point.
