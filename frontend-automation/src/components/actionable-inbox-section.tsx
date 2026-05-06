import type { WorkbenchSummary } from "@/lib/types";

export function ActionableInboxSection({ items }: { items: WorkbenchSummary["inbox"] }) {
  return (
    <section className="card p-4">
      <h3 className="text-lg font-semibold">Actionable Inbox</h3>
      <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => (
          <article key={item.key} className="rounded border border-slate-800 bg-slate-950/60 p-3">
            <p className="text-xs uppercase tracking-wide text-slate-500">{item.key.replaceAll("_", " ")}</p>
            <p className="mt-1 text-2xl font-semibold">{item.count}</p>
            <p className="mt-1 text-xs text-slate-400">Priority: {item.priority}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

