import type { TimelineEvent } from "@/lib/types";

export function Timeline({ items }: { items: TimelineEvent[] }) {
  return (
    <section className="card p-4">
      <h3 className="text-lg font-semibold">Conversation Timeline</h3>
      <div className="mt-3 space-y-2">
        {items.map((item, idx) => (
          <article key={`${item.kind}-${item.at}-${idx}`} className="rounded border border-slate-800 bg-slate-950/60 p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-semibold">{item.title}</p>
              <span className="text-xs text-slate-500">{new Date(item.at).toLocaleString()}</span>
            </div>
            <p className="mt-1 text-xs uppercase tracking-wide text-slate-500">{item.kind}</p>
            {item.campaign ? <p className="mt-1 text-xs text-slate-400">{item.campaign}</p> : null}
            {item.detail ? <p className="mt-2 text-sm text-slate-300">{item.detail}</p> : null}
          </article>
        ))}
      </div>
    </section>
  );
}

