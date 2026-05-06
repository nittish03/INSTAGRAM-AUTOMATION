"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Skeleton } from "@/components/skeleton";
import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";
import type { DashboardStats, GoogleStatus } from "@/lib/types";

const STATS_KEY = "home.stats";
const GOOGLE_KEY = "home.google";
const REFRESHED_KEY = "home.refreshedAt";

type ShortcutCard = {
  href: string;
  title: string;
  description: string;
};

const shortcuts: ShortcutCard[] = [
  { href: "/dashboard", title: "Control Center", description: "Live KPIs and pipeline overview." },
  { href: "/analytics", title: "Analytics", description: "Trends, deal states, daily activity." },
  { href: "/leads", title: "Leads", description: "Browse and filter all leads." },
  { href: "/deals", title: "Deals", description: "Pipeline by deal state." },
  { href: "/tasks", title: "Tasks", description: "Background task queue and statuses." },
  { href: "/messages", title: "Drafts (HITL)", description: "Approve outbound message drafts." },
  { href: "/campaigns", title: "Campaigns", description: "Configured outreach campaigns." },
  { href: "/linkedin-profiles", title: "LinkedIn Profiles", description: "Operator profiles and limits." },
  { href: "/search-keywords", title: "Search Keywords", description: "Per-campaign keywords pool." },
  { href: "/site-configuration", title: "Site Configuration", description: "LLM + Google Sheet sync." },
  { href: "/google", title: "Google Workspace", description: "Connection status and sheets." },
  { href: "/action-logs", title: "Action Logs", description: "Connect/follow-up audit trail." },
];

export default function HomePage() {
  const cachedStats = pageCache.get<DashboardStats>(STATS_KEY);
  const cachedGoogle = pageCache.get<GoogleStatus>(GOOGLE_KEY);
  const cachedRefreshed = pageCache.get<string>(REFRESHED_KEY);
  const [stats, setStats] = useState<DashboardStats | null>(cachedStats ?? null);
  const [google, setGoogle] = useState<GoogleStatus | null>(cachedGoogle ?? null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!cachedStats);
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(
    cachedRefreshed ? new Date(cachedRefreshed) : null,
  );

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const [d, g] = await Promise.all([api.dashboard(), api.googleStatus()]);
      setStats(d.stats);
      setGoogle(g.google);
      const now = new Date();
      setRefreshedAt(now);
      pageCache.set(STATS_KEY, d.stats);
      pageCache.set(GOOGLE_KEY, g.google);
      pageCache.set(REFRESHED_KEY, now.toISOString());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load home");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const [d, g] = await Promise.all([api.dashboard(), api.googleStatus()]);
        if (!mounted) return;
        setStats(d.stats);
        setGoogle(g.google);
        const now = new Date();
        setRefreshedAt(now);
        pageCache.set(STATS_KEY, d.stats);
        pageCache.set(GOOGLE_KEY, g.google);
        pageCache.set(REFRESHED_KEY, now.toISOString());
      } catch (e) {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : "Failed to load home");
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
      <PageHeader
        title="Welcome to Leadway"
        description="Quick access to every workspace and live snapshot of your outreach engine."
        actions={
          <div className="flex items-center gap-3 text-xs text-slate-400">
            {refreshedAt ? (
              <span>Updated {refreshedAt.toLocaleTimeString()}</span>
            ) : null}
            <button
              className="btn-secondary"
              onClick={() => void refresh()}
              disabled={loading}
            >
              {loading ? "Refreshing..." : "Refresh"}
            </button>
          </div>
        }
      />
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {(loading ? Array.from({ length: 8 }) : [
          { label: "Total Leads", value: stats?.totalLeads ?? 0 },
          { label: "Connected", value: stats?.connected ?? 0 },
          { label: "Drafts to Approve", value: stats?.draftsAwaitingApproval ?? 0 },
          { label: "Actions Today", value: stats?.actionsToday ?? 0 },
          { label: "Acceptance Rate", value: `${stats?.acceptanceRate ?? 0}%` },
          { label: "Conversion Rate", value: `${stats?.conversionRate ?? 0}%` },
          { label: "Pipeline Total", value: stats?.pipelineTotal ?? 0 },
          { label: "Google Connected", value: google?.connected ? "Yes" : "No" },
        ]).map((entry, idx) => (
          <article key={idx} className="card p-4">
            {loading ? (
              <>
                <Skeleton className="h-3 w-24" />
                <Skeleton className="mt-3 h-8 w-20" />
              </>
            ) : (
              <>
                <p className="text-xs uppercase tracking-wide text-slate-400">
                  {(entry as { label: string }).label}
                </p>
                <p className="mt-2 text-2xl font-semibold">
                  {(entry as { value: string | number }).value}
                </p>
              </>
            )}
          </article>
        ))}
      </section>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {shortcuts.map((s) => (
          <Link key={s.href} href={s.href} className="card p-4 transition hover:border-violet-500">
            <p className="text-base font-semibold text-slate-100">{s.title}</p>
            <p className="mt-1 text-xs text-slate-400">{s.description}</p>
          </Link>
        ))}
      </section>
    </div>
  );
}
