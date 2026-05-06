"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { TableSkeleton } from "@/components/skeleton";
import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";
import type { ActionLog } from "@/lib/types";
import { useDebouncedValue } from "@/lib/use-debounced-value";

const CACHE_KEY = "action-logs.paged";
const PAGE_SIZE = 100;

type CachedActionLogs = {
  items: ActionLog[];
  page: number;
  hasMore: boolean;
};

export default function ActionLogsPage() {
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  const debouncedQ = useDebouncedValue(q.trim(), 300);
  const queryKey = `${CACHE_KEY}:${debouncedQ}:${type}:${status}`;
  const cached = pageCache.get<CachedActionLogs>(queryKey);
  const [allItems, setAllItems] = useState<ActionLog[]>(cached?.items ?? []);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!cached);
  const [loadingMore, setLoadingMore] = useState(false);
  const [currentPage, setCurrentPage] = useState(cached?.page ?? 0);
  const [hasMore, setHasMore] = useState(cached?.hasMore ?? true);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  async function loadPage(targetPage: number, replace = false, key = queryKey) {
    if (loadingMore || (!replace && !hasMore && key === queryKey)) return;
    setLoadingMore(true);
    try {
      const p = new URLSearchParams();
      p.set("page", String(targetPage));
      p.set("pageSize", String(PAGE_SIZE));
      if (debouncedQ) p.set("q", debouncedQ);
      if (type) p.set("type", type);
      if (status) p.set("status", status);
      const data = await api.actionLogs(p);
      const nextItems = replace ? data.items : [...allItems, ...data.items];
      const nextHasMore = nextItems.length < data.pagination.total;
      setAllItems(nextItems);
      setCurrentPage(targetPage);
      setHasMore(nextHasMore);
      pageCache.set<CachedActionLogs>(key, {
        items: nextItems,
        page: targetPage,
        hasMore: nextHasMore,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load action logs");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    let cancelled = false;
    const cacheHit = pageCache.get<CachedActionLogs>(queryKey);
    if (cacheHit) {
      setAllItems(cacheHit.items);
      setCurrentPage(cacheHit.page);
      setHasMore(cacheHit.hasMore);
      setLoading(false);
    } else {
      setAllItems([]);
      setCurrentPage(0);
      setHasMore(true);
      setLoading(true);
    }

    const loadInitialPage = async () => {
      setLoadingMore(true);
      try {
        const p = new URLSearchParams();
        p.set("page", "1");
        p.set("pageSize", String(PAGE_SIZE));
        if (debouncedQ) p.set("q", debouncedQ);
        if (type) p.set("type", type);
        if (status) p.set("status", status);
        const data = await api.actionLogs(p);
        if (cancelled) return;
        const nextItems = data.items;
        const nextHasMore = nextItems.length < data.pagination.total;
        setAllItems(nextItems);
        setCurrentPage(1);
        setHasMore(nextHasMore);
        pageCache.set<CachedActionLogs>(queryKey, {
          items: nextItems,
          page: 1,
          hasMore: nextHasMore,
        });
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load action logs");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    };

    void loadInitialPage();

    return () => {
      cancelled = true;
    };
  }, [debouncedQ, queryKey, status, type]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const filtered = useMemo(() => allItems, [allItems]);
  const totalLoaded = allItems.length;

  function onScroll() {
    const el = scrollRef.current;
    if (!el || loading || loadingMore || !hasMore) return;
    const thresholdPx = 120;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceToBottom <= thresholdPx) {
      void loadPage(currentPage + 1);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Action Logs"
        description="Connect / follow-up history with status, target, and operator details."
        actions={
          <>
            <input
              className="input max-w-[240px]"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search target, profile, campaign, or note"
            />
            <select
              className="input max-w-[160px]"
              value={type}
              onChange={(e) => setType(e.target.value)}
            >
              <option value="">All types</option>
              <option value="connect">connect</option>
              <option value="follow_up">follow_up</option>
            </select>
            <select
              className="input max-w-[160px]"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
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
      ) : filtered.length === 0 ? (
        <EmptyState title="No action logs found" description="Once the bot connects or follows up with leads, entries appear here." />
      ) : (
        <section className="card overflow-hidden">
          <div
            ref={scrollRef}
            onScroll={onScroll}
            className="h-[calc(100vh-15rem)] min-h-88 overflow-auto"
          >
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
              {filtered.map((a) => (
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
              <div className="border-t border-slate-800 px-4 py-3 text-center text-xs text-slate-400">
                {loadingMore
                  ? "Loading more action logs..."
                  : hasMore
                    ? "Scroll down to load more"
                    : `All loaded (${totalLoaded})`}
              </div>
            </div>
        </section>
      )}
    </div>
  );
}
