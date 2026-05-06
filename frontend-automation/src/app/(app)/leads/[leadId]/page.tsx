"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { PageHeader } from "@/components/page-header";
import { QualityScoreBadge } from "@/components/quality-score-badge";
import { ReasonList } from "@/components/reason-list";
import { Timeline } from "@/components/timeline";
import { api } from "@/lib/api";
import type { LeadInsights, TimelineEvent } from "@/lib/types";

export default function LeadDetailPage() {
  const params = useParams<{ leadId: string }>();
  const leadId = Number(params.leadId);
  const [insights, setInsights] = useState<LeadInsights | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!leadId) return;
    (async () => {
      try {
        const [i, t] = await Promise.all([api.leadInsights(leadId), api.leadTimeline(leadId)]);
        setInsights(i.insights);
        setTimeline(t.items);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load lead detail");
      }
    })();
  }, [leadId]);

  return (
    <div className="space-y-4">
      <PageHeader title={`Lead Detail #${leadId}`} description="Quality insights, conflicts, and full timeline." />
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {insights ? (
        <section className="card grid gap-4 p-4 md:grid-cols-2">
          <div className="space-y-3">
            <QualityScoreBadge score={insights.qualityScore} />
            <p className="text-sm text-slate-300">Next action: {insights.nextAction}</p>
          </div>
          <ReasonList title="Conflicts" items={insights.conflicts.length ? insights.conflicts : ["No conflicts found."]} />
          <div className="md:col-span-2">
            <ReasonList title="Scoring reasons" items={insights.reasons} />
          </div>
        </section>
      ) : null}
      <Timeline items={timeline} />
    </div>
  );
}

