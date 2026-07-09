import { ChatPanel } from "@/components/chat-panel";

export default function Home() {
  return (
    <main className="min-h-screen px-4 py-5 text-[var(--graphite)] sm:px-6 lg:px-8">
      <div className="mx-auto flex min-h-[calc(100vh-2.5rem)] max-w-[1500px] flex-col gap-5">
        <header className="workbench-panel rounded-[6px] px-5 py-4 sm:px-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl">
              <p className="font-data text-xs uppercase tracking-[0.22em] text-[var(--rdf)]">
                Ontology QA workbench
              </p>
              <h1 className="font-display mt-2 text-3xl font-semibold tracking-[-0.02em] text-[var(--graphite)] sm:text-4xl">
                Ask the graph. Inspect the proof.
              </h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-[var(--muted)] sm:text-base">
                A compact demo for Vietnamese natural-language questions over
                DBpedia/GraphDB, with each search, inspection, and SPARQL
                execution exposed as evidence.
              </p>
            </div>
            <div className="grid grid-cols-3 overflow-hidden rounded-[6px] border border-[var(--line)] bg-white/70 text-center text-xs">
              <div className="border-r border-[var(--line)] px-4 py-3">
                <div className="font-data text-[var(--rdf)]">search</div>
                <div className="mt-1 text-[var(--muted)]">ground terms</div>
              </div>
              <div className="border-r border-[var(--line)] px-4 py-3">
                <div className="font-data text-[var(--blueprint)]">inspect</div>
                <div className="mt-1 text-[var(--muted)]">read facts</div>
              </div>
              <div className="px-4 py-3">
                <div className="font-data text-[var(--query)]">execute</div>
                <div className="mt-1 text-[var(--muted)]">run SPARQL</div>
              </div>
            </div>
          </div>
        </header>

        <ChatPanel />
      </div>
    </main>
  );
}
