"use client";

import { useEffect, useState } from "react";

import { CampaignHealthCard } from "@/components/campaign-health-card";
import { PageHeader } from "@/components/page-header";
import { api } from "@/lib/api";
import type { CampaignHealthItem } from "@/lib/types";

export default function CampaignHealthPage() {
  const [items, setItems] = useState<CampaignHealthItem[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const data = await api.campaignHealth();
        setItems(data.items);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load campaign health");
      }
    })();
  }, []);

  return (
    <div className="space-y-4">
      <PageHeader title="Campaign Health" description="Monitor campaign quality, outcomes, and operational risk." />
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => (
          <CampaignHealthCard key={item.campaignId} item={item} />
        ))}
      </section>
    </div>
  );
}

