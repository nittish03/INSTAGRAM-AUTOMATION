"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { Skeleton } from "@/components/skeleton";
import type { DashboardStats } from "@/lib/types";

const emptyStats: DashboardStats = {
  totalLeads: 0,
  pipelineTotal: 0,
  connected: 0,
  pending: 0,
  failed: 0,
  completed: 0,
  actionsToday: 0,
  actionsWeek: 0,
  acceptanceRate: 0,
  conversionRate: 0,
  draftsAwaitingApproval: 0,
};

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats>(emptyStats);
  const [google, setGoogle] = useState<{ connected: boolean; email: string }>({
    connected: false,
    email: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null);

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const data = await api.dashboard();
      setStats(data.stats);
      setGoogle(data.google);
      setRefreshedAt(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <div className="space-y-4">
      <section className="card flex flex-wrap items-start justify-between gap-3 p-5">
        <div>
          <h2 className="text-2xl font-semibold">Control Center</h2>
          <p className="mt-1 text-sm text-slate-400">
            Monitor the full outreach pipeline and approve outbound drafts.
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-400">
          {refreshedAt ? <span>Updated {refreshedAt.toLocaleTimeString()}</span> : null}
          <button
            className="btn-secondary"
            onClick={() => void refresh()}
            disabled={loading}
          >
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </section>

      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {(loading
          ? [
              ["", ""],
              ["", ""],
              ["", ""],
              ["", ""],
              ["", ""],
              ["", ""],
              ["", ""],
              ["", ""],
            ]
          : [
              ["Total Leads", stats.totalLeads],
              ["Connected", stats.connected],
              ["Pending", stats.pending],
              ["Drafts Awaiting Approval", stats.draftsAwaitingApproval],
              ["Actions Today", stats.actionsToday],
              ["Acceptance Rate", `${stats.acceptanceRate}%`],
              ["Conversion Rate", `${stats.conversionRate}%`],
              ["Completed", stats.completed],
            ]
        ).map(([label, value], idx) => (
          <article key={loading ? `sk-${idx}` : String(label)} className="card p-4">
            {loading ? (
              <>
                <Skeleton className="h-3 w-24" />
                <Skeleton className="mt-3 h-8 w-20" />
              </>
            ) : (
              <>
                <p className="text-xs uppercase tracking-wide text-slate-400">{label}</p>
                <p className="mt-2 text-2xl font-semibold">{value}</p>
              </>
            )}
          </article>
        ))}
      </section>

      <section className="card p-5">
        <h3 className="text-lg font-semibold">Google Workspace</h3>
        {loading ? (
          <div className="mt-2 space-y-2">
            <Skeleton className="h-4 w-44" />
            <Skeleton className="h-4 w-64" />
          </div>
        ) : (
          <>
            <p className="mt-2 text-sm text-slate-300">
              Status:{" "}
              <span className={google.connected ? "text-emerald-400" : "text-rose-400"}>
                {google.connected ? "Connected" : "Disconnected"}
              </span>
            </p>
            <p className="mt-1 text-sm text-slate-400">{google.email || "No Google account attached."}</p>
          </>
        )}
      </section>
    </div>
  );
}
