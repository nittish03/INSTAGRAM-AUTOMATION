"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";
import { TableSkeleton } from "@/components/skeleton";
import type { Lead } from "@/lib/types";
import { useDebouncedValue } from "@/lib/use-debounced-value";

const CACHE_KEY = "leads.paged";
const PAGE_SIZE = 100;

type CachedLeads = {
  items: Lead[];
  page: number;
  hasMore: boolean;
};

export default function LeadsPage() {
  const [q, setQ] = useState("");
  const [state, setState] = useState("");
  const debouncedQ = useDebouncedValue(q.trim(), 300);
  const queryKey = `${CACHE_KEY}:${debouncedQ}:${state}`;
  const cached = pageCache.get<CachedLeads>(queryKey);
  const [allItems, setAllItems] = useState<Lead[]>(cached?.items ?? []);
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
      const data = await api.leads(p);
      const nextItems = replace ? data.items : [...allItems, ...data.items];
      const nextHasMore = nextItems.length < data.pagination.total;
      setAllItems(nextItems);
      setPage(targetPage);
      setHasMore(nextHasMore);
      pageCache.set<CachedLeads>(key, {
        items: nextItems,
        page: targetPage,
        hasMore: nextHasMore,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load leads");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }

  useEffect(() => {
    const cacheHit = pageCache.get<CachedLeads>(queryKey);
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

  const items = useMemo(() => {
    return allItems;
  }, [allItems]);

  return (
    <div className="space-y-4">
      <section className="card p-5">
        <h2 className="text-2xl font-semibold">Leads</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <input className="input" placeholder="Search by name/company/public id" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="input" value={state} onChange={(e) => setState(e.target.value)}>
            <option value="">All states</option>
            <option value="Qualified">Qualified</option>
            <option value="Pending">Pending</option>
            <option value="Connected">Connected</option>
            <option value="Completed">Completed</option>
            <option value="Failed">Failed</option>
          </select>
          <a className="btn-secondary" href="/google" target="_blank" rel="noreferrer">
            Open Google Workspace
          </a>
        </div>
      </section>
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {loading ? (
        <TableSkeleton rows={8} cols={5} />
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
                <th className="th">Company</th>
                <th className="th">State</th>
                <th className="th">LinkedIn</th>
                <th className="th">Sheet Exported</th>
              </tr>
            </thead>
            <tbody>
              {items.map((l) => (
                <tr key={l.id}>
                  <td className="td">
                    <div>{l.fullName}</div>
                    <div className="text-xs text-slate-500">{l.publicIdentifier}</div>
                  </td>
                  <td className="td">{l.companyName || "-"}</td>
                  <td className="td">{l.state}</td>
                  <td className="td">
                    <a href={l.linkedinUrl} target="_blank" rel="noreferrer" className="text-violet-300 hover:underline">
                      Profile
                    </a>
                  </td>
                  <td className="td">{l.sheetExportedAt ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
              </table>
              <div className="border-t border-slate-800 px-4 py-3 text-center text-xs text-slate-400">
                {loadingMore
                  ? "Loading more leads..."
                  : hasMore
                    ? "Scroll down to load more"
                    : "All leads loaded"}
              </div>
            </div>
        </section>
      )}
    </div>
  );
}
