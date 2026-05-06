"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { TableSkeleton } from "@/components/skeleton";
import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";
import type { Campaign, SearchKeywordItem } from "@/lib/types";
import { useDebouncedValue } from "@/lib/use-debounced-value";

const KEYWORDS_KEY = "search-keywords.paged";
const CAMPAIGNS_KEY = "campaigns.list";
const PAGE_SIZE = 100;

type CachedKeywords = {
  items: SearchKeywordItem[];
  page: number;
  hasMore: boolean;
};

export default function SearchKeywordsPage() {
  const [q, setQ] = useState("");
  const [campaignFilter, setCampaignFilter] = useState("");
  const [usedFilter, setUsedFilter] = useState("");
  const debouncedQ = useDebouncedValue(q.trim(), 300);
  const queryKey = `${KEYWORDS_KEY}:${debouncedQ}:${campaignFilter}:${usedFilter}`;
  const cachedKeywords = pageCache.get<CachedKeywords>(queryKey);
  const cachedCampaigns = pageCache.get<Campaign[]>(CAMPAIGNS_KEY);
  const [campaigns, setCampaigns] = useState<Campaign[]>(cachedCampaigns ?? []);
  const [allItems, setAllItems] = useState<SearchKeywordItem[]>(cachedKeywords?.items ?? []);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!cachedKeywords);
  const [loadingMore, setLoadingMore] = useState(false);
  const [currentPage, setCurrentPage] = useState(cachedKeywords?.page ?? 0);
  const [hasMore, setHasMore] = useState(cachedKeywords?.hasMore ?? true);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const [newKeyword, setNewKeyword] = useState("");
  const [newCampaignId, setNewCampaignId] = useState<number | "">(
    cachedCampaigns?.[0]?.id ?? "",
  );
  const [creating, setCreating] = useState(false);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const c = await api.campaigns();
        if (!mounted) return;
        setCampaigns(c.items);
        pageCache.set(CAMPAIGNS_KEY, c.items);
        if (!cachedCampaigns?.length && c.items[0]) setNewCampaignId(c.items[0].id);
      } catch (e) {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : "Failed to load campaigns");
      }
    })();
    return () => {
      mounted = false;
    };
  }, [cachedCampaigns]);

  async function loadPage(targetPage: number, replace = false, showSkeleton = false, key = queryKey) {
    if (loadingMore || (!replace && !hasMore && key === queryKey)) return;
    if (showSkeleton) setLoading(true);
    setLoadingMore(true);
    try {
      const p = new URLSearchParams();
      p.set("page", String(targetPage));
      p.set("pageSize", String(PAGE_SIZE));
      if (debouncedQ) p.set("q", debouncedQ);
      if (campaignFilter) p.set("campaignId", campaignFilter);
      if (usedFilter) p.set("used", usedFilter);
      const data = await api.searchKeywords(p);
      const nextItems = replace ? data.items : [...allItems, ...data.items];
      const nextHasMore = nextItems.length < data.pagination.total;
      setAllItems(nextItems);
      setCurrentPage(targetPage);
      setHasMore(nextHasMore);
      pageCache.set<CachedKeywords>(key, {
        items: nextItems,
        page: targetPage,
        hasMore: nextHasMore,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load keywords");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    const cacheHit = pageCache.get<CachedKeywords>(queryKey);
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
        if (campaignFilter) p.set("campaignId", campaignFilter);
        if (usedFilter) p.set("used", usedFilter);
        const data = await api.searchKeywords(p);
        if (cancelled) return;
        const nextItems = data.items;
        const nextHasMore = nextItems.length < data.pagination.total;
        setAllItems(nextItems);
        setCurrentPage(1);
        setHasMore(nextHasMore);
        pageCache.set<CachedKeywords>(queryKey, {
          items: nextItems,
          page: 1,
          hasMore: nextHasMore,
        });
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load keywords");
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
  }, [campaignFilter, debouncedQ, queryKey, usedFilter]);
  /* eslint-enable react-hooks/set-state-in-effect */

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    if (!newCampaignId || !newKeyword.trim()) return;
    setCreating(true);
    setError("");
    try {
      await api.createSearchKeyword(Number(newCampaignId), newKeyword.trim());
      setNewKeyword("");
      pageCache.clear(queryKey);
      await loadPage(1, true, true, queryKey);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    } finally {
      setCreating(false);
    }
  }

  async function onDelete(id: number) {
    if (!confirm("Delete this keyword?")) return;
    try {
      await api.deleteSearchKeyword(id);
      pageCache.clear(queryKey);
      await loadPage(1, true, true, queryKey);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  const filtered = useMemo(() => allItems, [allItems]);
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
        title="Search Keywords"
        description="Per-campaign keyword pool used by the bot for prospect discovery."
        actions={
          <input
            className="input max-w-[260px]"
            placeholder="Search keyword or campaign"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        }
      />
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      <section className="card p-5">
        <h3 className="text-base font-semibold">Add keyword</h3>
        <form onSubmit={onCreate} className="mt-3 grid gap-3 md:grid-cols-[200px_1fr_auto]">
          <select
            className="input"
            value={newCampaignId}
            onChange={(e) =>
              setNewCampaignId(e.target.value ? Number(e.target.value) : "")
            }
          >
            <option value="">Select campaign</option>
            {campaigns.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <input
            className="input"
            placeholder="Keyword (e.g. CTO at fintech startup)"
            value={newKeyword}
            onChange={(e) => setNewKeyword(e.target.value)}
          />
          <button className="btn-primary" disabled={creating || !newCampaignId || !newKeyword.trim()}>
            {creating ? "Adding..." : "Add"}
          </button>
        </form>
      </section>

      <section className="card flex flex-wrap gap-3 p-5">
        <select
          className="input max-w-[220px]"
          value={campaignFilter}
          onChange={(e) => setCampaignFilter(e.target.value)}
        >
          <option value="">All campaigns</option>
          {campaigns.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <select
          className="input max-w-[160px]"
          value={usedFilter}
          onChange={(e) => setUsedFilter(e.target.value)}
        >
          <option value="">All</option>
          <option value="false">Unused</option>
          <option value="true">Used</option>
        </select>
      </section>

      {loading ? (
        <TableSkeleton rows={6} cols={4} />
      ) : filtered.length === 0 ? (
        <EmptyState title="No keywords found" description="Add keywords above to seed the bot." />
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
                <th className="th">Keyword</th>
                <th className="th">Campaign</th>
                <th className="th">Status</th>
                <th className="th">Used at</th>
                <th className="th">Action</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((k) => (
                <tr key={k.id}>
                  <td className="td">{k.keyword}</td>
                  <td className="td">{k.campaign.name}</td>
                  <td className="td">
                    <span
                      className={
                        k.used
                          ? "rounded bg-slate-500/15 px-2 py-1 text-xs text-slate-300"
                          : "rounded bg-violet-500/15 px-2 py-1 text-xs text-violet-300"
                      }
                    >
                      {k.used ? "used" : "fresh"}
                    </span>
                  </td>
                  <td className="td">{k.usedAt ? new Date(k.usedAt).toLocaleString() : "-"}</td>
                  <td className="td">
                    <button onClick={() => onDelete(k.id)} className="btn-secondary text-rose-300 hover:bg-rose-500/10">
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
              </table>
              <div className="border-t border-slate-800 px-4 py-3 text-center text-xs text-slate-400">
                {loadingMore
                  ? "Loading more keywords..."
                  : hasMore
                    ? "Scroll down to load more"
                    : `All loaded (${filtered.length})`}
              </div>
            </div>
        </section>
      )}
    </div>
  );
}
