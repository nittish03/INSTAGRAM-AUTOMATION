"use client";

import Link from "next/link";
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
  const [connecting, setConnecting] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newTitle, setNewTitle] = useState("");

  async function disconnectGoogle() {
    setError("");
    try {
      await api.googleDisconnect();
      pageCache.clear(STATUS_KEY);
      pageCache.clear(SHEETS_KEY);
      setStatus({ connected: false, email: "", scopes: [] });
      setSheets([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to disconnect Google");
    }
  }

  async function connectGoogle() {
    setError("");
    setConnecting(true);
    try {
      const res = await api.googleAuthUrl();
      window.location.href = res.authUrl;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start Google OAuth");
      setConnecting(false);
    }
  }

  async function createSheet() {
    setError("");
    setCreating(true);
    try {
      const created = await api.googleSheetCreate(newTitle.trim() || "Untitled spreadsheet");
      const createdItem: GoogleSheetItem = {
        id: created.item.id,
        name: created.item.name,
        webViewLink: created.item.webViewLink,
        modifiedTime: "",
        isConfiguredSheet: false,
      };
      const next = [createdItem, ...sheets];
      setSheets(next);
      pageCache.set(SHEETS_KEY, next);
      setNewTitle("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create sheet");
    } finally {
      setCreating(false);
    }
  }

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
            <button
              className="btn-secondary text-rose-300 hover:bg-rose-500/10"
              onClick={() => void disconnectGoogle()}
            >
              Disconnect
            </button>
          ) : (
            <button className="btn-primary" onClick={() => void connectGoogle()} disabled={connecting}>
              {connecting ? "Redirecting..." : "Connect Google"}
            </button>
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
            {status?.redirectUri ? (
              <div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/60 p-3 text-xs text-slate-400">
                <div className="mb-1 font-medium text-slate-300">
                  Authorized redirect URI (must match Google Cloud Console exactly)
                </div>
                <div className="flex items-center gap-2">
                  <code className="flex-1 break-all rounded bg-slate-900 px-2 py-1 font-mono text-[11px] text-violet-300">
                    {status.redirectUri}
                  </code>
                  <button
                    type="button"
                    className="btn-secondary text-xs"
                    onClick={() => void navigator.clipboard?.writeText(status.redirectUri || "")}
                  >
                    Copy
                  </button>
                </div>
                <p className="mt-2 text-[11px] text-slate-500">
                  Google Cloud Console → Credentials → your OAuth client → Authorized redirect URIs.
                  Keep only this one URI to avoid <code>redirect_uri_mismatch</code>.
                </p>
              </div>
            ) : null}
          </div>
        )}
      </section>

      <section>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-base font-semibold text-slate-200">Your spreadsheets</h3>
          {status?.connected ? (
            <div className="flex items-center gap-2">
              <input
                className="input w-64"
                placeholder="New spreadsheet title"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
              />
              <button className="btn-secondary" onClick={() => void createSheet()} disabled={creating}>
                {creating ? "Creating..." : "Create"}
              </button>
            </div>
          ) : null}
        </div>
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
                      <div className="flex items-center gap-3">
                        <Link href={`/google/sheets/${encodeURIComponent(s.id)}`} className="text-violet-300 hover:underline">
                          Open
                        </Link>
                        <a href={s.webViewLink} target="_blank" rel="noreferrer" className="text-slate-400 hover:underline">
                          Google ↗
                        </a>
                      </div>
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
