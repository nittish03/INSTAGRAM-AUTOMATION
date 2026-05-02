import type { ExportPreviewItem } from "@/lib/types";

export function ExportPreviewTable({
  exportable,
  skipped,
  selected,
  onToggle,
}: {
  exportable: ExportPreviewItem[];
  skipped: ExportPreviewItem[];
  selected: Record<number, boolean>;
  onToggle: (leadId: number) => void;
}) {
  return (
    <section className="card overflow-hidden">
      <div className="p-4">
        <h3 className="text-lg font-semibold">Export Preview</h3>
        <p className="mt-1 text-xs text-slate-500">Choose leads to export, then confirm.</p>
      </div>
      <table className="w-full">
        <thead>
          <tr>
            <th className="th">Pick</th>
            <th className="th">Lead</th>
            <th className="th">Campaign</th>
            <th className="th">Connected</th>
          </tr>
        </thead>
        <tbody>
          {exportable.map((item) => (
            <tr key={item.leadId}>
              <td className="td">
                <input type="checkbox" checked={!!selected[item.leadId]} onChange={() => onToggle(item.leadId)} />
              </td>
              <td className="td">{item.fullName}</td>
              <td className="td">{item.campaign}</td>
              <td className="td">{new Date(item.connectedAt).toLocaleDateString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="border-t border-slate-800 p-4">
        <p className="text-sm font-semibold text-slate-300">Skipped ({skipped.length})</p>
        <ul className="mt-2 space-y-1 text-xs text-slate-400">
          {skipped.slice(0, 20).map((item) => (
            <li key={`skipped-${item.leadId}`}>{item.fullName}: {item.reason}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}

