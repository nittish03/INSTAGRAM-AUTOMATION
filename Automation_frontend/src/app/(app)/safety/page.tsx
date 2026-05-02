"use client";

import { useEffect, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { SafeModeBanner } from "@/components/safe-mode-banner";
import { api } from "@/lib/api";
import type { SafeModeSettings } from "@/lib/types";

export default function SafetyPage() {
  const [settings, setSettings] = useState<SafeModeSettings | null>(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  async function load() {
    try {
      const data = await api.safeMode();
      setSettings(data.settings);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load safety settings");
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, []);

  async function save() {
    if (!settings) return;
    try {
      const data = await api.saveSafeMode(settings);
      setSettings(data.settings);
      setInfo("Safety settings saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save safety settings");
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Safety Controls" description="Set global guardrails for bulk actions and queueing." actions={<button className="btn-primary" onClick={() => void save()}>Save Safety</button>} />
      <SafeModeBanner settings={settings} />
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-300">{info}</p> : null}
      {settings ? (
        <section className="card grid gap-3 p-4 md:grid-cols-2">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings.enabled}
              onChange={(e) => setSettings((cur) => (cur ? { ...cur, enabled: e.target.checked } : cur))}
            />
            Enable safe mode
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={settings.globalPauseOutreach}
              onChange={(e) => setSettings((cur) => (cur ? { ...cur, globalPauseOutreach: e.target.checked } : cur))}
            />
            Global pause outreach
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-xs text-slate-500">Max bulk approve</span>
            <input
              className="input"
              type="number"
              min={1}
              value={settings.maxBulkApprove}
              onChange={(e) => setSettings((cur) => (cur ? { ...cur, maxBulkApprove: Number(e.target.value || 1) } : cur))}
            />
          </label>
          <label className="text-sm">
            <span className="mb-1 block text-xs text-slate-500">Max bulk export</span>
            <input
              className="input"
              type="number"
              min={1}
              value={settings.maxBulkExport}
              onChange={(e) => setSettings((cur) => (cur ? { ...cur, maxBulkExport: Number(e.target.value || 1) } : cur))}
            />
          </label>
        </section>
      ) : null}
    </div>
  );
}

