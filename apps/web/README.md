# CoachLens web app

This is the Next.js product shell: the Home command center at `/`, the review workspace at `/agent-insights` (Agent Insights), and display-only Training, Role-Play, and KPI Tracker pages. All read real M2/M3/AWS-3/AWS-4/AWS-5 API contracts; the workspace is where a human reviews diagnoses and runs intervention, solution validation, and design. See [the command center guide](../../docs/ui1-command-center.md) for the Home read-model.

```bash
npm ci
npm run dev
```

Open <http://localhost:3000>. Run `npm run lint`, `npm run typecheck`, and `npm run build` before committing frontend changes. See the [repository README](../../README.md) for backend setup and data-safety rules.
Run `npm run test` for interaction tests. See the [M4 guide](../../docs/m4-review-workspace.md) for the synthetic demo path and privacy boundary.
