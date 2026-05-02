"use client";

import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { api } from "@/lib/api";
import type { FollowupSuggestion } from "@/lib/types";

export default function FollowupSuggestionsPage() {
  const [items, setItems] = useState<FollowupSuggestion[]>([]);
  const [selected, setSelected] = useState<Record<number, boolean>>({});
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  async function load() {
    try {
      const data = await api.followupSuggestions();
      setItems(data.items);
      setSelected({});
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load suggestions");
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, []);

  const selectedLeadIds = useMemo(
    () => Object.entries(selected).filter(([, v]) => v).map(([k]) => Number(k)),
    [selected],
  );

  async function queueSelected() {
    try {
      const data = await api.queueFollowups(selectedLeadIds);
      setInfo(`Queued ${data.enqueued}, skipped ${data.skipped}.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Queueing failed");
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Follow-Up Suggestions"
        description="Review next best actions and queue follow-ups in batch."
        actions={<button className="btn-primary" onClick={() => void queueSelected()} disabled={!selectedLeadIds.length}>Queue Selected ({selectedLeadIds.length})</button>}
      />
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-300">{info}</p> : null}
      <section className="card overflow-hidden">
        <table className="w-full">
          <thead>
            <tr>
              <th className="th">Pick</th>
              <th className="th">Lead</th>
              <th className="th">Campaign</th>
              <th className="th">Suggested Action</th>
              <th className="th">Rationale</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.leadId}>
                <td className="td">
                  <input type="checkbox" checked={!!selected[item.leadId]} onChange={() => setSelected((cur) => ({ ...cur, [item.leadId]: !cur[item.leadId] }))} />
                </td>
                <td className="td">{item.fullName}</td>
                <td className="td">{item.campaign}</td>
                <td className="td">{item.action}</td>
                <td className="td">{item.rationale}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

