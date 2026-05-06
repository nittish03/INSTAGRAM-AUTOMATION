"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";
import { SafeModeBanner } from "@/components/safe-mode-banner";
import { Skeleton } from "@/components/skeleton";
import type { DaemonLogsPayload, DaemonStatus, DashboardStats, SafeModeSettings } from "@/lib/types";

const STATS_KEY = "dashboard.stats";
const GOOGLE_KEY = "dashboard.google";
const REFRESHED_KEY = "dashboard.refreshedAt";

type DashboardTab = "overview" | "daemonLogs";

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
  const [info, setInfo] = useState("");
  const [safeMode, setSafeMode] = useState<SafeModeSettings | null>(null);
  const [daemon, setDaemon] = useState<DaemonStatus | null>(null);
  const [daemonLoading, setDaemonLoading] = useState(true);
  const [daemonMutating, setDaemonMutating] = useState(false);
  const [daemonLogs, setDaemonLogs] = useState<DaemonLogsPayload | null>(null);
  const [daemonLogsLoading, setDaemonLogsLoading] = useState(false);
  const [daemonLogsUpdatedAt, setDaemonLogsUpdatedAt] = useState<Date | null>(null);
  const [tab, setTab] = useState<DashboardTab>("overview");
  const [loading, setLoading] = useState(!cachedStats);
  const latestDaemonActionStartedAt = useRef(0);
  const daemonActionInFlight = useRef(false);
  const logsRef = useRef<HTMLDivElement | null>(null);
  const autoScrollLogs = useRef(true);
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(
    cachedRefreshed ? new Date(cachedRefreshed) : null,
  );

  async function refresh() {
    const statusRequestStartedAt = Date.now();
    setLoading(true);
    setDaemonLoading(true);
    setError("");
    setInfo("");
    try {
      const [data, safe, daemonStatus] = await Promise.all([
        api.dashboard(),
        api.safeMode(),
        api.daemonStatus(),
      ]);
      setStats(data.stats);
      setGoogle(data.google);
      setSafeMode(safe.settings);
      if (!daemonActionInFlight.current && statusRequestStartedAt > latestDaemonActionStartedAt.current) {
        setDaemon(daemonStatus.daemon);
      }
      const now = new Date();
      setRefreshedAt(now);
      pageCache.set(STATS_KEY, data.stats);
      pageCache.set(GOOGLE_KEY, data.google);
      pageCache.set(REFRESHED_KEY, now.toISOString());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load dashboard");
    } finally {
      setLoading(false);
      setDaemonLoading(false);
    }
  }

  async function refreshDaemonLogs() {
    setDaemonLogsLoading(true);
    try {
      const data = await api.daemonLogs(400);
      setDaemonLogs(data.logs);
      setDaemonLogsUpdatedAt(new Date());
      setDaemon(data.daemon);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load daemon logs");
    } finally {
      setDaemonLogsLoading(false);
    }
  }

  useEffect(() => {
    let mounted = true;
    (async () => {
      const statusRequestStartedAt = Date.now();
      try {
        const [data, safe, daemonStatus] = await Promise.all([
          api.dashboard(),
          api.safeMode(),
          api.daemonStatus(),
        ]);
        if (!mounted) return;
        setStats(data.stats);
        setGoogle(data.google);
        setSafeMode(safe.settings);
        if (!daemonActionInFlight.current && statusRequestStartedAt > latestDaemonActionStartedAt.current) {
          setDaemon(daemonStatus.daemon);
        }
        const now = new Date();
        setRefreshedAt(now);
        pageCache.set(STATS_KEY, data.stats);
        pageCache.set(GOOGLE_KEY, data.google);
        pageCache.set(REFRESHED_KEY, now.toISOString());
      } catch (e) {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : "Failed to load dashboard");
      } finally {
        if (mounted) {
          setLoading(false);
          setDaemonLoading(false);
        }
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (tab !== "daemonLogs") return;
    let stopped = false;
    void (async () => {
      if (!stopped) await refreshDaemonLogs();
    })();
    const t = window.setInterval(() => {
      void refreshDaemonLogs();
    }, 2000);
    return () => {
      stopped = true;
      window.clearInterval(t);
    };
  }, [tab]);

  useEffect(() => {
    if (tab !== "daemonLogs" || !autoScrollLogs.current) return;
    const node = logsRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [daemonLogs, tab]);

  async function toggleDaemon() {
    latestDaemonActionStartedAt.current = Date.now();
    daemonActionInFlight.current = true;
    setDaemonMutating(true);
    setError("");
    setInfo("");
    try {
      const data = daemon?.running ? await api.stopDaemon() : await api.launchDaemon();
      setDaemon(data.daemon);
      setInfo(data.daemon.running ? "Daemon is running." : "Daemon stopped.");
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : daemon?.running
            ? "Failed to stop daemon"
            : "Failed to launch daemon",
      );
    } finally {
      daemonActionInFlight.current = false;
      setDaemonMutating(false);
    }
  }

  function onLogsScroll() {
    const node = logsRef.current;
    if (!node) return;
    const nearBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 40;
    autoScrollLogs.current = nearBottom;
  }

  async function copyAllDaemonLogs() {
    const lines = daemonLogs?.lines ?? [];
    if (lines.length === 0) {
      setInfo("No daemon logs to copy yet.");
      return;
    }
    const text = lines.join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setInfo(`Copied ${lines.length} daemon log lines.`);
    } catch {
      setError("Failed to copy logs. Please allow clipboard access.");
    }
  }

  return (
    <div className="space-y-4">
      <section className="card flex flex-wrap items-start justify-between gap-3 p-5">
        <div>
          <h2 className="text-2xl font-semibold">Control Center</h2>
          <p className="mt-1 text-sm text-slate-400">
            Monitor the full outreach pipeline and approve outbound drafts.
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-3 text-xs text-slate-400">
          {refreshedAt ? <span>Updated {refreshedAt.toLocaleTimeString()}</span> : null}
          <span
            aria-live="polite"
            className={daemon?.running ? "text-emerald-400" : "text-slate-500"}
            role="status"
          >
            Daemon: {daemon?.running ? `Running${daemon.pid ? ` (#${daemon.pid})` : ""}` : "Stopped"}
          </span>
          <button
            className="btn-primary"
            onClick={() => void toggleDaemon()}
            disabled={daemonLoading || daemonMutating}
            title={
              daemonLoading
                ? "Checking daemon status"
                : daemon?.running
                  ? "Stop the running daemon"
                  : "Launch the local Leadway daemon"
            }
          >
            {daemonLoading
              ? "Checking Daemon..."
              : daemonMutating
                ? daemon?.running
                  ? "Stopping..."
                  : "Launching..."
                : daemon?.running
                  ? "Stop Daemon"
                  : "Run Daemon"}
          </button>
          <button
            className="btn-secondary"
            onClick={() => void refresh()}
            disabled={loading || daemonMutating}
          >
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </section>

      {error ? <p className="text-sm text-rose-400" role="alert">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-300" role="status">{info}</p> : null}
      <SafeModeBanner settings={safeMode} />

      <section className="card p-4 text-sm text-slate-300">
        <div className="flex flex-wrap gap-2">
          <button
            className={tab === "overview" ? "btn-primary" : "btn-secondary"}
            onClick={() => setTab("overview")}
          >
            Overview
          </button>
          <button
            className={tab === "daemonLogs" ? "btn-primary" : "btn-secondary"}
            onClick={() => setTab("daemonLogs")}
          >
            Daemon Logs (Live)
          </button>
          <a className="btn-secondary" href="/workbench">Open Workbench</a>
          <a className="btn-secondary" href="/campaign-health">Campaign Health</a>
          <a className="btn-secondary" href="/recovery">Recovery Center</a>
          <a className="btn-secondary" href="/export-center">Export Center</a>
        </div>
      </section>

      {tab === "overview" ? (
        <>
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
        </>
      ) : (
        <section className="card overflow-hidden p-0">
          <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3 text-xs text-slate-400">
            <div className="space-x-3">
              <span>{daemonLogs?.exists ? "Connected to daemon log file" : "Daemon log file not created yet"}</span>
              {daemonLogsUpdatedAt ? <span>Updated {daemonLogsUpdatedAt.toLocaleTimeString()}</span> : null}
              {daemon?.running ? <span className="text-emerald-400">Live daemon running</span> : <span>Daemon stopped</span>}
            </div>
            <button
              className="btn-secondary"
              onClick={() => void refreshDaemonLogs()}
              disabled={daemonLogsLoading}
            >
              {daemonLogsLoading ? "Refreshing..." : "Refresh logs"}
            </button>
            <button
              className="btn-secondary"
              onClick={() => void copyAllDaemonLogs()}
              disabled={!daemonLogs || daemonLogs.lines.length === 0}
              title="Copy all visible daemon log lines"
            >
              Copy all logs
            </button>
          </div>
          <div
            ref={logsRef}
            onScroll={onLogsScroll}
            className="h-[calc(100vh-18rem)] min-h-96 overflow-auto bg-slate-950/60 p-4 font-mono text-xs leading-5 text-slate-200"
          >
            {!daemonLogs || daemonLogs.lines.length === 0 ? (
              <p className="text-slate-500">No daemon logs yet. Start the daemon to stream logs here.</p>
            ) : (
              daemonLogs.lines.map((line, idx) => (
                <div key={`${idx}-${line.slice(0, 24)}`} className="whitespace-pre-wrap break-words">
                  {line}
                </div>
              ))
            )}
          </div>
        </section>
      )}
    </div>
  );
}
