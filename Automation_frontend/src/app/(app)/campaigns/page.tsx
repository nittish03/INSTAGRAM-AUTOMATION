"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { TableSkeleton } from "@/components/skeleton";
import type { Campaign } from "@/lib/types";

export default function CampaignsPage() {
  const [items, setItems] = useState<Campaign[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const data = await api.campaigns();
        setItems(data.items);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load campaigns");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="space-y-4">
      <section className="card p-5">
        <h2 className="text-2xl font-semibold">Campaigns</h2>
        <p className="mt-1 text-sm text-slate-400">Configured campaigns from your Django backend.</p>
      </section>
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {loading ? (
        <TableSkeleton rows={6} cols={5} />
      ) : (
        <section className="card overflow-hidden">
          <table className="w-full">
            <thead>
              <tr>
                <th className="th">Name</th>
                <th className="th">Type</th>
                <th className="th">Action Fraction</th>
                <th className="th">Booking Link</th>
                <th className="th">Users</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td className="td">{c.name}</td>
                  <td className="td">{c.isFreemium ? "Freemium" : "Regular"}</td>
                  <td className="td">{c.actionFraction}</td>
                  <td className="td">
                    {c.bookingLink ? (
                      <a href={c.bookingLink} target="_blank" className="text-violet-300 hover:underline" rel="noreferrer">
                        Open
                      </a>
                    ) : (
                      "-"
                    )}
                  </td>
                  <td className="td">{c.users.join(", ") || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
