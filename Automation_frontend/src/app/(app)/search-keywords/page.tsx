"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { TableSkeleton } from "@/components/skeleton";
import { api } from "@/lib/api";
import type { Campaign, SearchKeywordItem } from "@/lib/types";

export default function SearchKeywordsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [items, setItems] = useState<SearchKeywordItem[]>([]);
  const [campaignFilter, setCampaignFilter] = useState("");
  const [usedFilter, setUsedFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const [newKeyword, setNewKeyword] = useState("");
  const [newCampaignId, setNewCampaignId] = useState<number | "">("");
  const [creating, setCreating] = useState(false);

  const params = useMemo(() => {
    const p = new URLSearchParams();
    p.set("page", String(page));
    p.set("pageSize", String(pageSize));
    if (campaignFilter) p.set("campaignId", campaignFilter);
    if (usedFilter) p.set("used", usedFilter);
    return p;
  }, [campaignFilter, usedFilter, page, pageSize]);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const c = await api.campaigns();
        if (!mounted) return;
        setCampaigns(c.items);
        if (c.items[0]) setNewCampaignId(c.items[0].id);
      } catch (e) {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : "Failed to load campaigns");
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  async function load() {
    setLoading(true);
    try {
      const data = await api.searchKeywords(params);
      setItems(data.items);
      setTotal(data.pagination.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load keywords");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      try {
        const data = await api.searchKeywords(params);
        if (!mounted) return;
        setItems(data.items);
        setTotal(data.pagination.total);
      } catch (e) {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : "Failed to load keywords");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [params]);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    if (!newCampaignId || !newKeyword.trim()) return;
    setCreating(true);
    setError("");
    try {
      await api.createSearchKeyword(Number(newCampaignId), newKeyword.trim());
      setNewKeyword("");
      await load();
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
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-4">
      <PageHeader
        title="Search Keywords"
        description="Per-campaign keyword pool used by the bot for prospect discovery."
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
          onChange={(e) => {
            setCampaignFilter(e.target.value);
            setPage(1);
          }}
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
          onChange={(e) => {
            setUsedFilter(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All</option>
          <option value="false">Unused</option>
          <option value="true">Used</option>
        </select>
      </section>

      {loading ? (
        <TableSkeleton rows={6} cols={4} />
      ) : items.length === 0 ? (
        <EmptyState title="No keywords found" description="Add keywords above to seed the bot." />
      ) : (
        <section className="card overflow-hidden">
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
              {items.map((k) => (
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
        </section>
      )}

      <div className="flex items-center justify-between text-sm text-slate-400">
        <span>
          Page {page} of {pageCount} - {total} total
        </span>
        <div className="flex gap-2">
          <button
            className="btn-secondary disabled:opacity-50"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Previous
          </button>
          <button
            className="btn-secondary disabled:opacity-50"
            disabled={page >= pageCount || loading}
            onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
