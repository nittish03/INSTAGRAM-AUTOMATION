"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";
import { TableSkeleton } from "@/components/skeleton";
import type { Deal } from "@/lib/types";
import { useDebouncedValue } from "@/lib/use-debounced-value";

const CACHE_KEY = "deals.paged";
const PAGE_SIZE = 100;

type CachedDeals = {
  items: Deal[];
  page: number;
  hasMore: boolean;
};

export default function DealsPage() {
  const [q, setQ] = useState("");
  const [state, setState] = useState("");
  const debouncedQ = useDebouncedValue(q.trim(), 300);
  const queryKey = `${CACHE_KEY}:${debouncedQ}:${state}`;
  const cached = pageCache.get<CachedDeals>(queryKey);
  const [allItems, setAllItems] = useState<Deal[]>(cached?.items ?? []);
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
      if (state) p.set("state", state);
      const data = await api.deals(p);
      const nextItems = replace ? data.items : [...allItems, ...data.items];
      const nextHasMore = nextItems.length < data.pagination.total;
      setAllItems(nextItems);
      setPage(targetPage);
      setHasMore(nextHasMore);
      pageCache.set<CachedDeals>(key, {
        items: nextItems,
        page: targetPage,
        hasMore: nextHasMore,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load deals");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    let cancelled = false;
    const cacheHit = pageCache.get<CachedDeals>(queryKey);
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

    const loadInitialPage = async () => {
      setLoadingMore(true);
      try {
        const p = new URLSearchParams();
        p.set("page", "1");
        p.set("pageSize", String(PAGE_SIZE));
        if (debouncedQ) p.set("q", debouncedQ);
        if (state) p.set("state", state);
        const data = await api.deals(p);
        if (cancelled) return;
        const nextItems = data.items;
        const nextHasMore = nextItems.length < data.pagination.total;
        setAllItems(nextItems);
        setPage(1);
        setHasMore(nextHasMore);
        pageCache.set<CachedDeals>(queryKey, {
          items: nextItems,
          page: 1,
          hasMore: nextHasMore,
        });
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load deals");
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
  }, [debouncedQ, queryKey, state]);
  /* eslint-enable react-hooks/set-state-in-effect */

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
    () => allItems.filter((d) => !state || d.state === state),
    [allItems, state],
  );

  return (
    <div className="space-y-4">
      <section className="card p-5">
        <h2 className="text-2xl font-semibold">Deals</h2>
        <p className="mt-1 text-sm text-slate-400">
          Use Campaign Health and Follow-up Suggestions for operator decisions.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <input
            className="input"
            placeholder="Search by lead, campaign, or reason"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <select className="input" value={state} onChange={(e) => setState(e.target.value)}>
            <option value="">All states</option>
            <option value="Qualified">Qualified</option>
            <option value="Pending">Pending</option>
            <option value="Connected">Connected</option>
            <option value="Completed">Completed</option>
            <option value="Failed">Failed</option>
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
                <th className="th">Lead</th>
                <th className="th">Campaign</th>
                <th className="th">State</th>
                <th className="th">Attempts</th>
                <th className="th">Backoff (h)</th>
                <th className="th">Reason</th>
                <th className="th">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((d) => (
                <tr key={d.id}>
                  <td className="td">{d.lead.name}</td>
                  <td className="td">{d.campaign.name}</td>
                  <td className="td">{d.state}</td>
                  <td className="td">{d.connectAttempts}</td>
                  <td className="td">{d.backoffHours}</td>
                  <td className="td">{d.reason || "-"}</td>
                  <td className="td">
                    <a className="text-violet-300 hover:underline" href="/follow-up-suggestions">
                      Suggestions
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
              </table>
              <div className="border-t border-slate-800 px-4 py-3 text-center text-xs text-slate-400">
                {loadingMore
                  ? "Loading more deals..."
                  : hasMore
                    ? "Scroll down to load more"
                    : "All deals loaded"}
              </div>
            </div>
        </section>
      )}
    </div>
  );
}
