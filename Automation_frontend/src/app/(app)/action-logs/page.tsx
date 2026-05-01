"use client";

import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { TableSkeleton } from "@/components/skeleton";
import { api } from "@/lib/api";
import type { ActionLog } from "@/lib/types";

export default function ActionLogsPage() {
  const [items, setItems] = useState<ActionLog[]>([]);
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const params = useMemo(() => {
    const p = new URLSearchParams();
    p.set("page", String(page));
    p.set("pageSize", String(pageSize));
    if (type) p.set("type", type);
    if (status) p.set("status", status);
    return p;
  }, [type, status, page, pageSize]);

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      try {
        const data = await api.actionLogs(params);
        if (!mounted) return;
        setItems(data.items);
        setTotal(data.pagination.total);
      } catch (e) {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : "Failed to load action logs");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [params]);

  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-4">
      <PageHeader
        title="Action Logs"
        description="Connect / follow-up history with status, target, and operator details."
        actions={
          <>
            <select
              className="input max-w-[160px]"
              value={type}
              onChange={(e) => {
                setType(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All types</option>
              <option value="connect">connect</option>
              <option value="follow_up">follow_up</option>
            </select>
            <select
              className="input max-w-[160px]"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All statuses</option>
              <option value="success">success</option>
              <option value="failed">failed</option>
            </select>
          </>
        }
      />
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      {loading ? (
        <TableSkeleton rows={8} cols={6} />
      ) : items.length === 0 ? (
        <EmptyState title="No action logs found" description="Once the bot connects or follows up with leads, entries appear here." />
      ) : (
        <section className="card overflow-hidden">
          <table className="w-full">
            <thead>
              <tr>
                <th className="th">When</th>
                <th className="th">Type</th>
                <th className="th">Status</th>
                <th className="th">Target</th>
                <th className="th">Profile</th>
                <th className="th">Campaign</th>
                <th className="th">Note</th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td className="td whitespace-nowrap">{new Date(a.createdAt).toLocaleString()}</td>
                  <td className="td">{a.actionType}</td>
                  <td className="td">
                    <span
                      className={
                        a.status === "success"
                          ? "rounded bg-emerald-500/15 px-2 py-1 text-xs text-emerald-300"
                          : "rounded bg-rose-500/15 px-2 py-1 text-xs text-rose-300"
                      }
                    >
                      {a.status}
                    </span>
                  </td>
                  <td className="td">
                    <div>{a.targetName || "-"}</div>
                    <div className="text-xs text-slate-500">{a.targetPublicId}</div>
                  </td>
                  <td className="td">{a.profile.djangoUser || a.profile.username}</td>
                  <td className="td">{a.campaign.name}</td>
                  <td className="td">{a.note ? a.note.slice(0, 80) : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <div className="flex items-center justify-between text-sm text-slate-400">
        <span>
          Page {page} of {pageCount} - {total} total
        </span>
        <div className="flex gap-2">
          <button
            className="btn-secondary disabled:opacity-50"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Previous
          </button>
          <button
            className="btn-secondary disabled:opacity-50"
            disabled={page >= pageCount || loading}
            onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
