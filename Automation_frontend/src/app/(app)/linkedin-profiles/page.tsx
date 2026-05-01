"use client";

import { useEffect, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { TableSkeleton } from "@/components/skeleton";
import { api } from "@/lib/api";
import type { LinkedInProfileItem } from "@/lib/types";

export default function LinkedinProfilesPage() {
  const [items, setItems] = useState<LinkedInProfileItem[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pendingId, setPendingId] = useState<number | null>(null);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const data = await api.linkedinProfiles();
      setItems(data.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load profiles");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const data = await api.linkedinProfiles();
        if (!mounted) return;
        setItems(data.items);
      } catch (e) {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : "Failed to load profiles");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  async function toggle(id: number) {
    setPendingId(id);
    try {
      await api.toggleLinkedinProfile(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Toggle failed");
    } finally {
      setPendingId(null);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="LinkedIn Profiles"
        description="Operator profiles powering outreach. Toggle activation and review rate limits."
      />
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      {loading ? (
        <TableSkeleton rows={4} cols={7} />
      ) : items.length === 0 ? (
        <EmptyState
          title="No LinkedIn profiles configured"
          description="Add a LinkedIn profile in the backend admin to start outreach."
        />
      ) : (
        <section className="card overflow-hidden">
          <table className="w-full">
            <thead>
              <tr>
                <th className="th">Operator</th>
                <th className="th">LinkedIn</th>
                <th className="th">Active</th>
                <th className="th">Cookies</th>
                <th className="th">Connect (D / W)</th>
                <th className="th">Follow-up (D)</th>
                <th className="th">Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id}>
                  <td className="td">
                    <div>{p.djangoUser}</div>
                    <div className="text-xs text-slate-500">{p.djangoEmail}</div>
                  </td>
                  <td className="td">{p.linkedinUsername}</td>
                  <td className="td">
                    <span
                      className={
                        p.active
                          ? "rounded bg-emerald-500/15 px-2 py-1 text-xs text-emerald-300"
                          : "rounded bg-slate-500/15 px-2 py-1 text-xs text-slate-300"
                      }
                    >
                      {p.active ? "Active" : "Paused"}
                    </span>
                  </td>
                  <td className="td">
                    <span
                      className={
                        p.hasCookies
                          ? "rounded bg-emerald-500/15 px-2 py-1 text-xs text-emerald-300"
                          : "rounded bg-rose-500/15 px-2 py-1 text-xs text-rose-300"
                      }
                    >
                      {p.hasCookies ? "Loaded" : "Missing"}
                    </span>
                  </td>
                  <td className="td">
                    {p.connectDailyLimit} / {p.connectWeeklyLimit}
                  </td>
                  <td className="td">{p.followUpDailyLimit}</td>
                  <td className="td">
                    <button
                      onClick={() => toggle(p.id)}
                      disabled={pendingId === p.id}
                      className="btn-secondary disabled:opacity-50"
                    >
                      {pendingId === p.id ? "Saving..." : p.active ? "Pause" : "Activate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
