# CoachLens web app

This is the Next.js product shell: the UI-1 Home command center at `/` and the Milestone 4 review workspace at `/agent-insights` (Agent Insights). Both read real M2/M3 API contracts; the workspace lets a human review diagnostic hypotheses. See [the UI-1 guide](../../docs/ui1-command-center.md) for the Home read-model.

```bash
npm ci
npm run dev
```

Open <http://localhost:3000>. Run `npm run lint`, `npm run typecheck`, and `npm run build` before committing frontend changes. See the [repository README](../../README.md) for backend setup and data-safety rules.
Run `npm run test` for interaction tests. See the [M4 guide](../../docs/m4-review-workspace.md) for the synthetic demo path and privacy boundary.
