"use client";

import { useEffect, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { RecoveryActionPanel } from "@/components/recovery-action-panel";
import { api } from "@/lib/api";
import type { RecoveryItem } from "@/lib/types";

export default function RecoveryPage() {
  const [items, setItems] = useState<RecoveryItem[]>([]);
  const [error, setError] = useState("");

  async function load() {
    try {
      const data = await api.recovery();
      setItems(data.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load recovery queue");
    }
  }

  async function retryTask(taskId: number) {
    try {
      await api.retryTask(taskId);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Retry failed");
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, []);

  return (
    <div className="space-y-4">
      <PageHeader title="Failure Recovery" description="Retry failed and skipped tasks without leaving the product workflow." />
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      <RecoveryActionPanel items={items} onRetry={retryTask} />
    </div>
  );
}

