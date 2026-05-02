"use client";

import { useEffect, useState } from "react";

import { ActionableInboxSection } from "@/components/actionable-inbox-section";
import { PageHeader } from "@/components/page-header";
import { SafeModeBanner } from "@/components/safe-mode-banner";
import { api } from "@/lib/api";
import type { SafeModeSettings, WorkbenchSummary } from "@/lib/types";

export default function WorkbenchPage() {
  const [data, setData] = useState<WorkbenchSummary | null>(null);
  const [safeMode, setSafeMode] = useState<SafeModeSettings | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [workbench, safe] = await Promise.all([api.workbench(), api.safeMode()]);
        setData(workbench);
        setSafeMode(safe.settings);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load workbench");
      }
    })();
  }, []);

  return (
    <div className="space-y-4">
      <PageHeader title="Workbench" description="Primary operating surface for outreach quality and safety." />
      <SafeModeBanner settings={safeMode} />
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {data ? (
        <>
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {Object.entries(data.stats).map(([key, value]) => (
              <article key={key} className="card p-4">
                <p className="text-xs uppercase tracking-wide text-slate-500">{key.replaceAll(/([A-Z])/g, " $1")}</p>
                <p className="mt-2 text-2xl font-semibold">{value}</p>
              </article>
            ))}
          </section>
          <ActionableInboxSection items={data.inbox} />
        </>
      ) : null}
    </div>
  );
}

