const principles = [
  { number: "01", title: "Measure with code", detail: "Validated calculations establish quantitative truth." },
  { number: "02", title: "Interpret with AI", detail: "Models explain evidence and propose hypotheses." },
  { number: "03", title: "Decide with people", detail: "Humans review diagnoses and approve interventions." },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-[#091821] text-[#eaf5f3]">
      <div className="mx-auto max-w-7xl px-6 sm:px-10 lg:px-16">
        <header className="flex items-center justify-between border-b border-white/10 py-6">
          <a href="#top" className="flex items-center gap-3" aria-label="CoachLens AI home">
            <span className="flex size-9 items-center justify-center rounded-xl border border-[#64d9c2]/40 bg-[#64d9c2]/10 text-[#94ead7]">
              <svg viewBox="0 0 24 24" fill="none" className="size-5" aria-hidden="true">
                <path d="M19 12a7 7 0 1 1-2.1-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                <path d="M12 12l6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                <circle cx="12" cy="12" r="2" fill="currentColor" />
              </svg>
            </span>
            <span className="text-lg font-semibold tracking-tight">CoachLens <span className="text-[#78ddca]">AI</span></span>
          </a>
          <nav className="hidden gap-8 text-sm text-[#a9c2c4] sm:flex" aria-label="Page navigation">
            <a className="hover:text-white" href="#approach">Approach</a>
            <a className="hover:text-white" href="#foundation">Foundation</a>
          </nav>
        </header>

        <main id="top">
          <section className="grid items-center gap-14 py-20 lg:min-h-[660px] lg:grid-cols-[1.1fr_0.9fr] lg:gap-20 lg:py-24">
            <div>
              <p className="mb-7 inline-flex items-center gap-3 rounded-full border border-[#6dddc9]/25 bg-[#6dddc9]/5 px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#90e8d7]">
                <span className="size-1.5 rounded-full bg-[#78ddca]" />
                Milestone 01 · Foundation
              </p>
              <h1 className="max-w-3xl text-5xl font-semibold leading-[1.07] tracking-[-0.055em] sm:text-6xl lg:text-[4.75rem]">
                A clearer path from <span className="text-[#82e1ce]">evidence</span> to better practice.
              </h1>
              <p className="mt-7 max-w-xl text-lg leading-8 text-[#afc7c8]">
                CoachLens is being built to connect QA evidence, careful analysis, human-reviewed decisions, and relevant training in one traceable workflow.
              </p>
              <a href="#approach" className="mt-9 inline-flex items-center gap-3 rounded-lg bg-[#8ce8d2] px-5 py-3.5 text-sm font-semibold text-[#0b2429] transition hover:bg-[#b3f5e5]">
                See the approach <span aria-hidden="true">↗</span>
              </a>
            </div>

            <div className="rounded-2xl border border-white/10 bg-[#102630] p-6 shadow-[0_30px_100px_rgba(0,0,0,0.2)] sm:p-8">
              <div className="flex items-center justify-between border-b border-white/10 pb-6">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#78ddca]">Product direction</p>
                  <p className="mt-2 text-lg font-medium">Evidence to action</p>
                </div>
                <span className="rounded-full border border-white/15 px-3 py-1 text-xs text-[#aac6c5]">Planned</span>
              </div>
              <ol className="mt-7 space-y-4" aria-label="Planned product workflow">
                <li className="flex gap-4 rounded-xl border border-[#7adfc9]/20 bg-[#7adfc9]/[0.08] p-4">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-[#79dec8]/15 text-[#a5efdf]">01</span>
                  <div><p className="font-medium">Source evidence</p><p className="mt-1 text-sm text-[#a9c5c5]">Validated QA records and quantitative signals</p></div>
                </li>
                <li className="flex gap-4 rounded-xl border border-white/10 bg-white/[0.035] p-4">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-white/10 text-[#d1e2df]">02</span>
                  <div><p className="font-medium">Reviewed diagnosis</p><p className="mt-1 text-sm text-[#a9c5c5]">Interpretation checked by a human</p></div>
                </li>
                <li className="flex gap-4 rounded-xl border border-white/10 bg-white/[0.035] p-4">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-white/10 text-[#d1e2df]">03</span>
                  <div><p className="font-medium">Relevant practice</p><p className="mt-1 text-sm text-[#a9c5c5]">Training tied back to the original evidence</p></div>
                </li>
              </ol>
              <p className="mt-6 border-t border-white/10 pt-5 text-xs leading-5 text-[#8eacad]">This is a product roadmap view. No QA data or analytics are shown.</p>
            </div>
          </section>

          <section id="approach" className="border-t border-white/10 py-16 sm:py-20">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#78ddca]">Guiding architecture</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">Trust has clear ownership.</h2>
            <div className="mt-10 grid gap-4 md:grid-cols-3">
              {principles.map((principle) => (
                <article key={principle.number} className="rounded-xl border border-white/10 bg-white/[0.035] p-6">
                  <span className="text-sm font-semibold text-[#78ddca]">{principle.number}</span>
                  <h3 className="mt-8 text-xl font-semibold">{principle.title}</h3>
                  <p className="mt-3 text-sm leading-6 text-[#a9c2c4]">{principle.detail}</p>
                </article>
              ))}
            </div>
          </section>

          <section id="foundation" className="flex flex-col justify-between gap-5 border-t border-white/10 py-10 sm:flex-row sm:items-center">
            <div><p className="text-sm font-semibold">The foundation is in place.</p><p className="mt-1 text-sm text-[#a9c2c4]">A frontend shell, API health check, architecture notes, and safeguards for raw data.</p></div>
            <span className="w-fit rounded-full border border-[#78ddca]/30 px-3 py-1.5 text-xs font-medium text-[#a3eedf]">Milestone 1</span>
          </section>
        </main>

        <footer className="flex flex-col gap-3 border-t border-white/10 py-7 text-xs text-[#8eacad] sm:flex-row sm:justify-between">
          <p>CoachLens AI · Evidence-driven performance improvement</p>
          <p>ResultsCX x AWS AI competition</p>
        </footer>
      </div>
    </div>
  );
}
