# UI-1: Home / Command Center

UI-1 adds a product shell and a Home page in front of the existing M4/M5 review workspace. Home answers "what is happening across my team, what needs attention, and where should I go next". The existing workspace, now reached as **Agent Insights**, still answers "why is this happening, what evidence supports it, how did CoachLens reason, and do I approve". Nothing in the review workspace's three-column evidence UI, its review actions, its AWS-3 semantic review panel, or its M5 design flow changed.

## Product sections

| Route | Section | Role | State in UI-1 | Data source |
| --- | --- | --- | --- | --- |
| `/` | Home | Command center: summarize observations and route | Implemented | M2 counts via M3 signals, M3 records, AWS-3 review, M5 design result, `/diagnostics/mode` |
| `/agent-insights` | Agent Insights | Deep diagnostic workspace (the existing review UI) | Implemented | M3 / M4 / AWS-3 / M5 as before |
| `/training` | Training | Downstream intervention and training design | Planned page | AWS-4, AWS-5 |
| `/role-play` | Role-Play | Practice simulation | Planned page | AWS-5 practice scenarios |
| `/kpi-tracker` | KPI Tracker | Outcome measurement | Planned page | Outcome evaluation |
| `/reports` | Reports | Impact reporting | Planned page | Outcome evaluation, AWS-6 |
| `/resources` | Resources | Methodology and evidence policy | Planned page | Documentation |

Planned pages (`apps/web/app/components/section-placeholder.tsx`) name the section's role, the lanes that will fill it, and link back to Home and Agent Insights. They contain no controls and no figures, so nothing on them can be mistaken for ResultsCX output. The sidebar (`apps/web/app/components/app-shell.tsx`) marks them "Planned".

## Progressive disclosure

```
Home (summary)
  -> Selected insight (first signal in backend failure-count order, with its latest record and review states)
    -> Agent Insights (link to /agent-insights?signal=<id>)
      -> Existing workspace: observed signal, hypothesis, semantic review, human decision, M5 design
```

Home summarizes; Agent Insights explains. Every number on Home is a link or one click from the rows behind it. The `signal` query parameter opens the workspace on that signal; an unknown id falls back to the backend's first signal without issuing an evidence request for the unknown id.

## Home sections

1. **Heading and provenance.** The provenance badge is built from `GET /diagnostics/mode`: synthetic demo, real ResultsCX (local), local normalized, no data loaded, or unknown when the route fails. Provider fields are echoed, so a label can never claim a provider that is not installed.
2. **Top summary** (four stat tiles): Agents monitored, Priority issues, Overall QA, Training / intervention. All are **pending** until their owning backend contracts provide them. Available M2 evaluation and criterion counts appear only as contextual notes.
3. **Observed QA criteria**: up to five signals in the backend's order (descending failure count, then failure rate). Zero-failure criteria can appear. Each row shows the backend's fail count, evaluated results, coverage, and a single-hue bar whose width is the backend `fail_rate`. The UI never re-sorts or recomputes.
4. **Selected insight**: the first ordered signal with its latest M3 record. Ordering is by observed failure count, not a priority or severity policy. Fields: performance issue, working diagnosis, working cause type, confidence (non-calibrated wording; fixture wording when the provider is the M4 demo fixture), evidence review (AWS-3), human validation (M4), explanation, semantic assessment, evidence preview (cited references and missing-evidence items from the current diagnosis), the primary CTA, and a recommended next step derived from the record state. An all-pass criterion with no diagnosis leads to evidence inspection, not a request for diagnosis.
5. **Downstream stages**: Intervention (AWS-4), Training (AWS-5), Alignment (AWS-6), Outcome. These render as blocked, not started, proposed, not applicable, or pending backend. "Proposed" appears only when an M5 design result exists for the validated diagnosis, and it always says the proposal is not yet validated.

## Semantics

- Before human validation the page says **working diagnosis**, **working cause type**, **evidence review**, **human validation**, and **recommended next step: review diagnosis**. It never says a root cause implies training. The semantic review label describes only the original provider proposal; it does not infer whether the separate validator was a fixture or AI from the diagnosis provider.
- Semantic **evidence questioned** uses the caution tone (amber). The rejected tone (red) is reserved for a human rejection. Approved and evidence validated share the validated tone (teal). Proposed uses a separate slate tone; pending backend uses a dashed neutral tone.
- Confidence keeps the workspace's language: a provider self-report or a fixed fixture value, not a statistically calibrated probability.
- The pipeline strip shows every stage of the intended workflow (observed, working diagnosis, evidence review, human validation, intervention, training, alignment, outcome) with its current, truthful status.

## Read-model architecture

```
apps/web/lib/home/read-model.ts   types + pure builder  buildHomeReadModel(HomeSources) -> HomeReadModel
apps/web/lib/home/load.ts         loader: fetches HomeSources through the existing api() helper
apps/web/app/command-center.tsx   CommandCenterView(model) pure view; CommandCenter default export loads and handles states
```

`HomeSources` is the raw backend material: the runtime mode, the signal list, and for the top signal its latest record, its stored semantic review (404 means none), and its design result when the record is validated (404 means none). `HomeReadModel` is display-ready and fully typed: `Provenance`, `SummaryMetric[]` with a `MetricReading` union (`available | pending | unavailable`), `PerformanceGap[]`, `PriorityInsight | null`, and `DownstreamStage[]`.

Rules enforced by the boundary:

- No QA statistics are calculated in React. The builder formats and maps backend values; the only arithmetic is a display percentage from the backend's `fail_rate` string.
- Unavailable data is an explicit state, not a zero and not a placeholder number.
- Fixture provenance is carried at two levels: the runtime mode badge, and per-record detection of the `m4-demo-fixture` provider, which switches the wording to "fixture" throughout. There is no frontend fixture mode; fixtures only ever come from the backend demo scripts, matching the existing repository pattern.

## Future backend wiring points

| Home slot | Today | Wire when merged |
| --- | --- | --- |
| Agents monitored | pending; shows `evaluation_count` | M2 agent roster route: add to `HomeSources`, set `reading.state = "available"` in `buildSummary` |
| Overall QA | pending; shows `signal_count` | M2 aggregate scoring route: same path |
| Intervention stage | blocked / not started / proposed (M5 result) | AWS-4 validated intervention: replace the `proposed` detail with the validation status in `buildDownstream` |
| Training stage | blocked / proposed (M5 outline) | AWS-5 training status: same |
| Alignment stage | pending backend | AWS-6 alignment status |
| Outcome stage | pending backend | Outcome evaluation |
| Priority issues tile | pending | A backend priority policy and count, if one is introduced |
| Training / intervention tile | pending | derive from the AWS-4 / AWS-5 fields above |

Each wiring change is a loader fetch in `load.ts` plus a mapping in `read-model.ts`; the view already renders every `DownstreamStage.status` and `MetricReading.state`. The AWS-4 and AWS-5 lanes' API contracts are not assumed anywhere in the frontend.

## States implemented

Loading (skeleton tiles with a status message), error (alert with retry and a route into Agent Insights), empty (no signals), real data, synthetic demo, awaiting human review, evidence validated, evidence questioned, approved, revised pending approval, revision approved, rejected, and downstream proposed / blocked / pending.

## Accessibility and demo notes

Semantic landmarks and heading levels (one `h1` per page, `h2` per section, `h3` per tile), a skip link, a `nav aria-label="Primary"` with `aria-current="page"`, links for navigation and buttons for actions only, a labeled `img` role for each gap bar, `role="status"` for loading and `role="alert"` for errors, and no interactive control that does nothing. The design targets desktop and collapses to a single column under 1250px and a horizontal nav under 900px.

## Tests

`apps/web/test/home-read-model.test.ts` covers the builder and loader; `apps/web/test/command-center.test.tsx` covers the view from a typed model, every status tone, the CTA, pending downstream slots, provenance separation, and loading / error / retry; `apps/web/test/agent-insights.test.tsx` covers the route into the existing workspace including the deep link and the unknown-id fallback; `apps/web/test/app-shell.test.tsx` covers the navigation and a planned page. The existing review and design workspace tests are unchanged.

## Limits

Home summarizes only the backend's first-ranked signal; there is no per-agent view because no route exposes agent identity aggregates, and Home deliberately does not fetch reviewer evidence rows (which contain raw evaluator feedback). Review state is process-local in the API and disappears on restart, so Home reflects only the current process.
