"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";
import { SafeModeBanner } from "@/components/safe-mode-banner";
import { Skeleton } from "@/components/skeleton";
import type { DashboardStats, SafeModeSettings } from "@/lib/types";

const STATS_KEY = "dashboard.stats";
const GOOGLE_KEY = "dashboard.google";
const REFRESHED_KEY = "dashboard.refreshedAt";

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
  const cachedStats = pageCache.get<DashboardStats>(STATS_KEY);
  const cachedGoogle = pageCache.get<{ connected: boolean; email: string }>(GOOGLE_KEY);
  const cachedRefreshed = pageCache.get<string>(REFRESHED_KEY);
  const [stats, setStats] = useState<DashboardStats>(cachedStats ?? emptyStats);
  const [google, setGoogle] = useState<{ connected: boolean; email: string }>(
    cachedGoogle ?? { connected: false, email: "" },
  );
  const [error, setError] = useState("");
  const [safeMode, setSafeMode] = useState<SafeModeSettings | null>(null);
  const [loading, setLoading] = useState(!cachedStats);
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(
    cachedRefreshed ? new Date(cachedRefreshed) : null,
  );

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const data = await api.dashboard();
      const safe = await api.safeMode();
      setStats(data.stats);
      setGoogle(data.google);
      setSafeMode(safe.settings);
      const now = new Date();
      setRefreshedAt(now);
      pageCache.set(STATS_KEY, data.stats);
      pageCache.set(GOOGLE_KEY, data.google);
      pageCache.set(REFRESHED_KEY, now.toISOString());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const data = await api.dashboard();
        const safe = await api.safeMode();
        if (!mounted) return;
        setStats(data.stats);
        setGoogle(data.google);
        setSafeMode(safe.settings);
        const now = new Date();
        setRefreshedAt(now);
        pageCache.set(STATS_KEY, data.stats);
        pageCache.set(GOOGLE_KEY, data.google);
        pageCache.set(REFRESHED_KEY, now.toISOString());
      } catch (e) {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : "Failed to load dashboard");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
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
      <SafeModeBanner settings={safeMode} />

      <section className="card p-4 text-sm text-slate-300">
        <div className="flex flex-wrap gap-2">
          <a className="btn-secondary" href="/workbench">Open Workbench</a>
          <a className="btn-secondary" href="/campaign-health">Campaign Health</a>
          <a className="btn-secondary" href="/recovery">Recovery Center</a>
          <a className="btn-secondary" href="/export-center">Export Center</a>
        </div>
      </section>

      <section className="grid auto-rows-fr gap-4 md:grid-cols-2 xl:grid-cols-4">
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
          <article
            key={loading ? `sk-${idx}` : String(label)}
            className="card flex h-full min-h-[5.5rem] flex-col justify-between p-4"
          >
            {loading ? (
              <>
                <Skeleton className="h-3 w-24" />
                <Skeleton className="mt-3 h-8 w-20" />
              </>
            ) : (
              <>
                <p className="min-h-[2.5rem] text-xs uppercase leading-snug tracking-wide text-slate-400">
                  {label}
                </p>
                <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
              </>
            )}
          </article>
        ))}
      </section>

      <section className="card shrink-0 p-5">
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
