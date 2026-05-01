"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";
import { TableSkeleton } from "@/components/skeleton";
import type { TaskItem } from "@/lib/types";
import { useDebouncedValue } from "@/lib/use-debounced-value";

const CACHE_KEY = "tasks.paged";
const PAGE_SIZE = 100;

type CachedTasks = {
  items: TaskItem[];
  page: number;
  hasMore: boolean;
};

export default function TasksPage() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const debouncedQ = useDebouncedValue(q.trim(), 300);
  const queryKey = `${CACHE_KEY}:${debouncedQ}:${status}`;
  const cached = pageCache.get<CachedTasks>(queryKey);
  const [allItems, setAllItems] = useState<TaskItem[]>(cached?.items ?? []);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!cached);
  const [loadingMore, setLoadingMore] = useState(false);
  const [page, setPage] = useState(cached?.page ?? 0);
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
      if (status) p.set("status", status);
      const data = await api.tasks(p);
      const nextItems = replace ? data.items : [...allItems, ...data.items];
      const nextHasMore = nextItems.length < data.pagination.total;
      setAllItems(nextItems);
      setPage(targetPage);
      setHasMore(nextHasMore);
      pageCache.set<CachedTasks>(key, {
        items: nextItems,
        page: targetPage,
        hasMore: nextHasMore,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load tasks");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }

  useEffect(() => {
    const cacheHit = pageCache.get<CachedTasks>(queryKey);
    if (cacheHit) {
      setAllItems(cacheHit.items);
      setPage(cacheHit.page);
      setHasMore(cacheHit.hasMore);
      setLoading(false);
    } else {
      setAllItems([]);
      setPage(0);
      setHasMore(true);
      setLoading(true);
    }
    void loadPage(1, true, queryKey);
  }, [queryKey]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el || loading || loadingMore || !hasMore) return;
    const thresholdPx = 120;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceToBottom <= thresholdPx) {
      void loadPage(page + 1);
    }
  }

  const items = useMemo(
    () => allItems.filter((t) => !status || t.status === status),
    [allItems, status],
  );

  return (
    <div className="space-y-4">
      <section className="card p-5">
        <h2 className="text-2xl font-semibold">Task Queue</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <input
            className="input"
            placeholder="Search by task type, status, error, or lead"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            <option value="pending">pending</option>
            <option value="running">running</option>
            <option value="completed">completed</option>
            <option value="failed">failed</option>
            <option value="skipped">skipped</option>
          </select>
        </div>
      </section>
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {loading ? (
        <TableSkeleton rows={8} cols={6} />
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
              <div className="border-t border-slate-800 px-4 py-3 text-center text-xs text-slate-400">
                {loadingMore
                  ? "Loading more tasks..."
                  : hasMore
                    ? "Scroll down to load more"
                    : "All tasks loaded"}
              </div>
            </div>
        </section>
      )}
    </div>
  );
}
