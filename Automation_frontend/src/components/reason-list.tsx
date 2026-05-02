export function ReasonList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</p>
      <ul className="space-y-1 text-sm text-slate-300">
        {items.map((item, idx) => (
          <li key={`${idx}-${item}`} className="rounded border border-slate-800 bg-slate-950/50 px-2 py-1">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

