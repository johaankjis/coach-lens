# CoachLens AI

CoachLens AI is an evidence-driven performance diagnosis and training platform for the ResultsCX x AWS AI competition. Its planned workflow connects QA evidence to quantitative analysis, human-validated diagnosis, selected interventions, practice, and outcome measurement. Milestone 1 provides only the repository foundation; it does not process competition data or produce diagnoses.

## Repository structure

| Path | Purpose |
| --- | --- |
| `apps/web` | Minimal Next.js frontend shell |
| `services/api` | FastAPI service with a health endpoint |
| `packages/contracts` | Reserved for future shared contracts |
| `data/raw` | Local supplied datasets; Git ignores all contents except `.gitkeep` |
| `data/processed` | Reserved for derived data; local contents are Git-ignored |
| `docs` | Product and architecture notes |
| `scripts` | Reserved for development utilities |

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
npm --prefix apps/web run lint
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

Never commit supplied ResultsCX healthcare QA datasets. Keep them under `data/raw`, whose contents are ignored by Git except for the directory marker. Derived files under `data/processed` are also ignored. Do not use `git add -f` on these directories or commit credentials in `.env` files.

See [product spec](docs/product-spec.md) and [architecture](docs/architecture.md) for the intended later system.
