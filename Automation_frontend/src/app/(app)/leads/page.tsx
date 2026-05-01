"use client";

import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import { TableSkeleton } from "@/components/skeleton";
import type { Lead } from "@/lib/types";

export default function LeadsPage() {
  const [items, setItems] = useState<Lead[]>([]);
  const [q, setQ] = useState("");
  const [state, setState] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const params = useMemo(() => {
    const p = new URLSearchParams();
    p.set("page", "1");
    p.set("pageSize", "100");
    if (q) p.set("q", q);
    if (state) p.set("state", state);
    return p;
  }, [q, state]);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const data = await api.leads(params);
        setItems(data.items);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load leads");
      } finally {
        setLoading(false);
      }
    })();
  }, [params]);

  return (
    <div className="space-y-4">
      <section className="card p-5">
        <h2 className="text-2xl font-semibold">Leads</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <input className="input" placeholder="Search by name/company/public id" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="input" value={state} onChange={(e) => setState(e.target.value)}>
            <option value="">All states</option>
            <option value="Qualified">Qualified</option>
            <option value="Pending">Pending</option>
            <option value="Connected">Connected</option>
            <option value="Completed">Completed</option>
            <option value="Failed">Failed</option>
          </select>
          <a className="btn-secondary" href="/google" target="_blank" rel="noreferrer">
            Open Google Workspace
          </a>
        </div>
      </section>
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {loading ? (
        <TableSkeleton rows={8} cols={5} />
      ) : (
        <section className="card overflow-hidden">
          <table className="w-full">
            <thead>
              <tr>
                <th className="th">Lead</th>
                <th className="th">Company</th>
                <th className="th">State</th>
                <th className="th">LinkedIn</th>
                <th className="th">Sheet Exported</th>
              </tr>
            </thead>
            <tbody>
              {items.map((l) => (
                <tr key={l.id}>
                  <td className="td">
                    <div>{l.fullName}</div>
                    <div className="text-xs text-slate-500">{l.publicIdentifier}</div>
                  </td>
                  <td className="td">{l.companyName || "-"}</td>
                  <td className="td">{l.state}</td>
                  <td className="td">
                    <a href={l.linkedinUrl} target="_blank" rel="noreferrer" className="text-violet-300 hover:underline">
                      Profile
                    </a>
                  </td>
                  <td className="td">{l.sheetExportedAt ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
