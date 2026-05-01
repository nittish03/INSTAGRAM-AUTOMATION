"use client";

import { useEffect, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Skeleton } from "@/components/skeleton";
import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";
import type { AnalyticsData } from "@/lib/types";

const RANGE_OPTIONS = [7, 14, 30, 60];
const dataKey = (d: number) => `analytics.data.${d}`;
const refreshedKey = (d: number) => `analytics.refreshedAt.${d}`;

export default function AnalyticsPage() {
  const [days, setDays] = useState(14);
  const cachedData = pageCache.get<AnalyticsData>(dataKey(days));
  const cachedRefreshed = pageCache.get<string>(refreshedKey(days));
  const [data, setData] = useState<AnalyticsData | null>(cachedData ?? null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!cachedData);
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(
    cachedRefreshed ? new Date(cachedRefreshed) : null,
  );

  async function refresh(d: number) {
    setLoading(true);
    setError("");
    try {
      const res = await api.analytics(d);
      setData(res);
      const now = new Date();
      setRefreshedAt(now);
      pageCache.set(dataKey(d), res);
      pageCache.set(refreshedKey(d), now.toISOString());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let mounted = true;
    const cached = pageCache.get<AnalyticsData>(dataKey(days));
    if (cached) {
      setData(cached);
      const r = pageCache.get<string>(refreshedKey(days));
      setRefreshedAt(r ? new Date(r) : null);
      setLoading(false);
    } else {
      setLoading(true);
    }
    setError("");
    (async () => {
      try {
        const res = await api.analytics(days);
        if (!mounted) return;
        setData(res);
        const now = new Date();
        setRefreshedAt(now);
        pageCache.set(dataKey(days), res);
        pageCache.set(refreshedKey(days), now.toISOString());
      } catch (e) {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : "Failed to load analytics");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [days]);

  const dailyMax =
    data?.daily.reduce((m, d) => Math.max(m, d.connect + d.followUp), 0) || 1;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Analytics"
        description="Outreach activity, deal states, and task queue health."
        actions={
          <>
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="input max-w-[160px]"
            >
              {RANGE_OPTIONS.map((d) => (
                <option key={d} value={d}>
                  Last {d} days
                </option>
              ))}
            </select>
            {refreshedAt ? (
              <span className="self-center text-xs text-slate-400">
                Updated {refreshedAt.toLocaleTimeString()}
              </span>
            ) : null}
            <button
              className="btn-secondary"
              onClick={() => void refresh(days)}
              disabled={loading}
            >
              {loading ? "Refreshing..." : "Refresh"}
            </button>
          </>
        }
      />
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      <section className="grid gap-4 md:grid-cols-2">
        <div className="card p-5">
          <h3 className="text-base font-semibold">Daily activity</h3>
          {loading ? (
            <div className="mt-4 space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-6 w-full" />
              ))}
            </div>
          ) : !data || data.daily.length === 0 ? (
            <p className="mt-3 text-sm text-slate-400">No activity yet in this range.</p>
          ) : (
            <div className="mt-4 space-y-2">
              {data.daily.map((row) => {
                const total = row.connect + row.followUp;
                const widthPct = (total / dailyMax) * 100;
                return (
                  <div key={row.date} className="flex items-center gap-3">
                    <span className="w-24 text-xs text-slate-400">{row.date}</span>
                    <div className="flex-1 overflow-hidden rounded-md bg-slate-900">
                      <div className="flex h-5">
                        <div
                          className="bg-violet-500"
                          style={{ width: `${(row.connect / dailyMax) * 100}%` }}
                          title={`Connects: ${row.connect}`}
                        />
                        <div
                          className="bg-emerald-500"
                          style={{ width: `${(row.followUp / dailyMax) * 100}%` }}
                          title={`Follow-ups: ${row.followUp}`}
                        />
                      </div>
                    </div>
                    <span className="w-12 text-right text-xs text-slate-400">
                      {total} ({Math.round(widthPct)}%)
                    </span>
                  </div>
                );
              })}
              <div className="mt-3 flex items-center gap-4 text-xs text-slate-400">
                <span className="inline-flex items-center gap-2">
                  <span className="inline-block h-3 w-3 rounded bg-violet-500" /> Connect
                </span>
                <span className="inline-flex items-center gap-2">
                  <span className="inline-block h-3 w-3 rounded bg-emerald-500" /> Follow-up
                </span>
              </div>
            </div>
          )}
        </div>

        <div className="card p-5">
          <h3 className="text-base font-semibold">Deal states</h3>
          {loading ? (
            <Skeleton className="mt-4 h-32 w-full" />
          ) : !data || data.dealStates.length === 0 ? (
            <p className="mt-3 text-sm text-slate-400">No deals yet.</p>
          ) : (
            <ul className="mt-3 space-y-2 text-sm">
              {data.dealStates.map((row) => (
                <li key={row.state} className="flex items-center justify-between border-b border-slate-800 py-2">
                  <span className="text-slate-300">{row.state}</span>
                  <span className="font-semibold text-slate-100">{row.count}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card p-5">
          <h3 className="text-base font-semibold">Task queue</h3>
          {loading ? (
            <Skeleton className="mt-4 h-32 w-full" />
          ) : !data || data.taskStates.length === 0 ? (
            <p className="mt-3 text-sm text-slate-400">No tasks yet.</p>
          ) : (
            <ul className="mt-3 space-y-2 text-sm">
              {data.taskStates.map((row) => (
                <li key={row.status} className="flex items-center justify-between border-b border-slate-800 py-2">
                  <span className="text-slate-300">{row.status}</span>
                  <span className="font-semibold text-slate-100">{row.count}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card p-5">
          <h3 className="text-base font-semibold">Top campaigns</h3>
          {loading ? (
            <Skeleton className="mt-4 h-32 w-full" />
          ) : !data || data.topCampaigns.length === 0 ? (
            <EmptyState title="No campaigns with deals yet" />
          ) : (
            <ul className="mt-3 space-y-2 text-sm">
              {data.topCampaigns.map((row) => (
                <li key={row.id} className="flex items-center justify-between border-b border-slate-800 py-2">
                  <span className="text-slate-300">{row.name || `Campaign #${row.id}`}</span>
                  <span className="font-semibold text-slate-100">{row.count}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}
