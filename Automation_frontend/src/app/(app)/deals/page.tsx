"use client";

import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import { TableSkeleton } from "@/components/skeleton";
import type { Deal } from "@/lib/types";

export default function DealsPage() {
  const [items, setItems] = useState<Deal[]>([]);
  const [state, setState] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const params = useMemo(() => {
    const p = new URLSearchParams();
    p.set("page", "1");
    p.set("pageSize", "100");
    if (state) p.set("state", state);
    return p;
  }, [state]);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const data = await api.deals(params);
        setItems(data.items);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load deals");
      } finally {
        setLoading(false);
      }
    })();
  }, [params]);

  return (
    <div className="space-y-4">
      <section className="card p-5">
        <h2 className="text-2xl font-semibold">Deals</h2>
        <select className="input mt-4 max-w-xs" value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">All states</option>
          <option value="Qualified">Qualified</option>
          <option value="Pending">Pending</option>
          <option value="Connected">Connected</option>
          <option value="Completed">Completed</option>
          <option value="Failed">Failed</option>
        </select>
      </section>
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {loading ? (
        <TableSkeleton rows={8} cols={6} />
      ) : (
        <section className="card overflow-hidden">
          <table className="w-full">
            <thead>
              <tr>
                <th className="th">Lead</th>
                <th className="th">Campaign</th>
                <th className="th">State</th>
                <th className="th">Attempts</th>
                <th className="th">Backoff (h)</th>
                <th className="th">Reason</th>
              </tr>
            </thead>
            <tbody>
              {items.map((d) => (
                <tr key={d.id}>
                  <td className="td">{d.lead.name}</td>
                  <td className="td">{d.campaign.name}</td>
                  <td className="td">{d.state}</td>
                  <td className="td">{d.connectAttempts}</td>
                  <td className="td">{d.backoffHours}</td>
                  <td className="td">{d.reason || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
