"use client";

import { useEffect, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { SafeModeBanner } from "@/components/safe-mode-banner";
import { api } from "@/lib/api";
import type { SafeModeSettings } from "@/lib/types";

const helpText = {
  safeMode:
    "Adds guardrails to risky bulk actions. It does not stop the Instagram worker daemon by itself; it mainly limits how many items can be approved or exported at once.",
  globalPause:
    "Hard pause for outreach queueing from product workflows. Use this when you want to stop operator-triggered DM actions broadly.",
  pauseInvites:
    "Stops only fresh top-of-funnel outreach expansion (discover → qualify → new DM drafts). Existing drafts, approvals, sends, reply checks, and follow-up bumps can still continue.",
  maxBulkApprove:
    "Maximum number of drafts or retry actions allowed in one bulk operation while safe mode is enabled.",
  maxBulkExport:
    "Maximum number of leads allowed in one bulk export while safe mode is enabled.",
};

function HelpTip({ label, text }: { label: string; text: string }) {
  return (
    <span className="group relative inline-flex">
      <span
        aria-label={`${label}: ${text}`}
        className="inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full border border-slate-600 text-[10px] font-semibold text-slate-400 transition-colors group-hover:border-slate-400 group-hover:text-slate-200"
        tabIndex={0}
        title={text}
      >
        i
      </span>
      <span className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 w-64 -translate-x-1/2 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs leading-relaxed text-slate-200 opacity-0 shadow-xl transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
        {text}
      </span>
    </span>
  );
}

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
          <div className="flex items-center gap-2 text-sm">
            <input
              id="safe-mode-enabled"
              type="checkbox"
              checked={settings.enabled}
              onChange={(e) => setSettings((cur) => (cur ? { ...cur, enabled: e.target.checked } : cur))}
            />
            <label htmlFor="safe-mode-enabled">Enable safe mode</label>
            <HelpTip label="Enable safe mode" text={helpText.safeMode} />
          </div>
          <div className="flex items-center gap-2 text-sm">
            <input
              id="global-pause-outreach"
              type="checkbox"
              checked={settings.globalPauseOutreach}
              onChange={(e) => setSettings((cur) => (cur ? { ...cur, globalPauseOutreach: e.target.checked } : cur))}
            />
            <label htmlFor="global-pause-outreach">Global pause outreach</label>
            <HelpTip label="Global pause outreach" text={helpText.globalPause} />
          </div>
          <div className="flex items-start gap-2 text-sm md:col-span-2">
            <input
              id="pause-new-follows"
              className="mt-1"
              type="checkbox"
              checked={settings.pauseNewFollows}
              onChange={(e) => setSettings((cur) => (cur ? { ...cur, pauseNewFollows: e.target.checked } : cur))}
            />
            <span>
              <span className="inline-flex items-center gap-1.5">
                <label htmlFor="pause-new-follows">Pause new outreach</label>
                <HelpTip label="Pause new outreach" text={helpText.pauseInvites} />
              </span>
              <span className="mt-1 block text-xs text-slate-500">
                Stops discover → qualify → new DM drafts while allowing existing drafts, approvals, sends, and reply checks to continue.
              </span>
            </span>
          </div>
          <div className="text-sm">
            <span className="mb-1 inline-flex items-center gap-1.5 text-xs text-slate-500">
              <label htmlFor="max-bulk-approve">Max bulk approve</label>
              <HelpTip label="Max bulk approve" text={helpText.maxBulkApprove} />
            </span>
            <input
              id="max-bulk-approve"
              className="input"
              type="number"
              min={1}
              value={settings.maxBulkApprove}
              onChange={(e) => setSettings((cur) => (cur ? { ...cur, maxBulkApprove: Number(e.target.value || 1) } : cur))}
            />
          </div>
          <div className="text-sm">
            <span className="mb-1 inline-flex items-center gap-1.5 text-xs text-slate-500">
              <label htmlFor="max-bulk-export">Max bulk export</label>
              <HelpTip label="Max bulk export" text={helpText.maxBulkExport} />
            </span>
            <input
              id="max-bulk-export"
              className="input"
              type="number"
              min={1}
              value={settings.maxBulkExport}
              onChange={(e) => setSettings((cur) => (cur ? { ...cur, maxBulkExport: Number(e.target.value || 1) } : cur))}
            />
          </div>
        </section>
      ) : null}
    </div>
  );
}

