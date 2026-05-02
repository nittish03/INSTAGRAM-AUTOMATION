import type { RecoveryItem } from "@/lib/types";

export function RecoveryActionPanel({
  items,
  onRetry,
}: {
  items: RecoveryItem[];
  onRetry: (taskId: number) => void;
}) {
  return (
    <section className="card p-4">
      <h3 className="text-lg font-semibold">Failure Recovery Center</h3>
      <div className="mt-3 space-y-2">
        {items.map((item) => (
          <article key={item.taskId} className="rounded border border-slate-800 bg-slate-950/60 p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-semibold">
                #{item.taskId} {item.taskType} ({item.status})
              </p>
              <button className="btn-secondary" onClick={() => onRetry(item.taskId)}>
                Retry
              </button>
            </div>
            <p className="mt-2 text-sm text-slate-300">{item.error || "No error details."}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

