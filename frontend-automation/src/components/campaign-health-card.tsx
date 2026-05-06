import type { CampaignHealthItem } from "@/lib/types";

export function CampaignHealthCard({ item }: { item: CampaignHealthItem }) {
  return (
    <article className="card p-4">
      <p className="text-lg font-semibold">{item.campaignName}</p>
      <p className="mt-1 text-xs text-slate-500">Health score {item.healthScore}</p>
      <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
        <p>Deals: {item.totalDeals}</p>
        <p>Connected: {item.connected}</p>
        <p>Pending: {item.pending}</p>
        <p>Failed: {item.failed}</p>
        <p>Acceptance: {item.acceptanceRate}%</p>
        <p>Conversion: {item.conversionRate}%</p>
      </div>
    </article>
  );
}

