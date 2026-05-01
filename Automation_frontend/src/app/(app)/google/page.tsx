"use client";

import { useEffect, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Skeleton, TableSkeleton } from "@/components/skeleton";
import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";
import type { GoogleSheetItem, GoogleStatus } from "@/lib/types";

const STATUS_KEY = "google.status";
const SHEETS_KEY = "google.sheets";

export default function GooglePage() {
  const cachedStatus = pageCache.get<GoogleStatus>(STATUS_KEY);
  const cachedSheets = pageCache.get<GoogleSheetItem[]>(SHEETS_KEY);
  const [status, setStatus] = useState<GoogleStatus | null>(cachedStatus ?? null);
  const [sheets, setSheets] = useState<GoogleSheetItem[]>(cachedSheets ?? []);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!cachedStatus);
  const [sheetsLoading, setSheetsLoading] = useState(false);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const s = await api.googleStatus();
        if (!mounted) return;
        setStatus(s.google);
        pageCache.set(STATUS_KEY, s.google);
        if (s.google.connected) {
          if (!cachedSheets) setSheetsLoading(true);
          try {
            const list = await api.googleSheets();
            if (!mounted) return;
            setSheets(list.items);
            pageCache.set(SHEETS_KEY, list.items);
          } finally {
            if (mounted) setSheetsLoading(false);
          }
        }
      } catch (e) {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : "Failed to load Google status");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [cachedSheets]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Google Workspace"
        description="OAuth status, connected account, and your spreadsheets."
        actions={
          status?.connected ? (
            <form action="/oauth/google/disconnect" method="post">
              <button className="btn-secondary text-rose-300 hover:bg-rose-500/10">
                Disconnect
              </button>
            </form>
          ) : (
            <a href="/oauth/google/start" className="btn-primary">
              Connect Google
            </a>
          )
        }
      />
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      <section className="card p-5">
        <h3 className="text-base font-semibold">Connection</h3>
        {loading ? (
          <div className="mt-3 space-y-2">
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-4 w-64" />
          </div>
        ) : (
          <div className="mt-3 space-y-2 text-sm">
            <div>
              Status:{" "}
              <span className={status?.connected ? "text-emerald-400" : "text-rose-400"}>
                {status?.connected ? "Connected" : "Disconnected"}
              </span>
            </div>
            <div className="text-slate-400">
              {status?.connected ? status.email : "Connect your Google account to enable Sheet sync."}
            </div>
            {status?.scopes && status.scopes.length > 0 ? (
              <div className="text-xs text-slate-500">
                Scopes: {status.scopes.join(", ")}
              </div>
            ) : null}
          </div>
        )}
      </section>

      <section>
        <h3 className="mb-2 text-base font-semibold text-slate-200">Your spreadsheets</h3>
        {!status?.connected && !loading ? (
          <EmptyState
            title="Google account not connected"
            description="Click Connect Google above to authorize Sheet sync."
          />
        ) : sheetsLoading ? (
          <TableSkeleton rows={5} cols={3} />
        ) : sheets.length === 0 ? (
          <EmptyState title="No spreadsheets found" description="Create a sheet in Google to see it here." />
        ) : (
          <div className="card overflow-hidden">
            <div className="h-[calc(100vh-15rem)] min-h-88 overflow-auto">
              <table className="w-full">
              <thead>
                <tr>
                  <th className="th">Name</th>
                  <th className="th">Last modified</th>
                  <th className="th">Action</th>
                </tr>
              </thead>
              <tbody>
                {sheets.map((s) => (
                  <tr key={s.id}>
                    <td className="td">
                      <div className="flex items-center gap-2">
                        <span>{s.name}</span>
                        {s.isConfiguredSheet ? (
                          <span className="rounded bg-violet-500/20 px-2 py-0.5 text-xs text-violet-300">
                            Site Config
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td className="td">
                      {s.modifiedTime ? new Date(s.modifiedTime).toLocaleString() : "-"}
                    </td>
                    <td className="td">
                      <a
                        href={s.webViewLink}
                        target="_blank"
                        rel="noreferrer"
                        className="text-violet-300 hover:underline"
                      >
                        Open
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
