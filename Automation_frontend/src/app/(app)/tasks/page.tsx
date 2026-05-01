"use client";

import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import { TableSkeleton } from "@/components/skeleton";
import type { TaskItem } from "@/lib/types";

export default function TasksPage() {
  const [items, setItems] = useState<TaskItem[]>([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const params = useMemo(() => {
    const p = new URLSearchParams();
    p.set("page", "1");
    p.set("pageSize", "100");
    if (status) p.set("status", status);
    return p;
  }, [status]);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const data = await api.tasks(params);
        setItems(data.items);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load tasks");
      } finally {
        setLoading(false);
      }
    })();
  }, [params]);

  return (
    <div className="space-y-4">
      <section className="card p-5">
        <h2 className="text-2xl font-semibold">Task Queue</h2>
        <select className="input mt-4 max-w-xs" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="pending">pending</option>
          <option value="running">running</option>
          <option value="completed">completed</option>
          <option value="failed">failed</option>
          <option value="skipped">skipped</option>
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
                <th className="th">ID</th>
                <th className="th">Type</th>
                <th className="th">Status</th>
                <th className="th">Scheduled</th>
                <th className="th">Deal</th>
                <th className="th">Error</th>
              </tr>
            </thead>
            <tbody>
              {items.map((t) => (
                <tr key={t.id}>
                  <td className="td">{t.id}</td>
                  <td className="td">{t.taskType}</td>
                  <td className="td">{t.status}</td>
                  <td className="td">{new Date(t.scheduledAt).toLocaleString()}</td>
                  <td className="td">{t.dealId ?? "-"}</td>
                  <td className="td">{t.error ? t.error.slice(0, 80) : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
