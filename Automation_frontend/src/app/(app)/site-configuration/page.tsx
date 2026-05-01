"use client";

import { FormEvent, useEffect, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Skeleton } from "@/components/skeleton";
import { api } from "@/lib/api";
import type { SiteConfig } from "@/lib/types";

type FormState = SiteConfig & { llmApiKey?: string };

const blank: FormState = {
  llmProvider: "openai",
  aiModel: "",
  llmApiBase: "",
  azureDeployment: "",
  azureApiVersion: "",
  hasLlmApiKey: false,
  googleSheetSyncEnabled: false,
  googleSheetId: "",
  googleSheetTab: "Sheet1",
  googleSheetSyncUserId: null,
  llmApiKey: "",
};

export default function SiteConfigurationPage() {
  const [form, setForm] = useState<FormState>(blank);
  const [initialForm, setInitialForm] = useState<FormState>(blank);
  const [providers, setProviders] = useState<{ value: string; label: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      try {
        const res = await api.siteConfig();
        if (!mounted) return;
        const loaded = { ...res.config, llmApiKey: "" };
        setForm(loaded);
        setInitialForm(loaded);
        setProviders(res.providerChoices);
      } catch (e) {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : "Failed to load settings");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  const hasChanges =
    form.llmProvider !== initialForm.llmProvider ||
    form.aiModel !== initialForm.aiModel ||
    form.llmApiBase !== initialForm.llmApiBase ||
    form.azureDeployment !== initialForm.azureDeployment ||
    form.azureApiVersion !== initialForm.azureApiVersion ||
    form.googleSheetSyncEnabled !== initialForm.googleSheetSyncEnabled ||
    form.googleSheetId !== initialForm.googleSheetId ||
    form.googleSheetTab !== initialForm.googleSheetTab ||
    (form.llmApiKey || "").trim().length > 0;

  async function onSave(e: FormEvent) {
    e.preventDefault();
    if (!hasChanges) return;
    setSaving(true);
    setError("");
    setInfo("");
    try {
      await api.saveSiteConfig({
        llmProvider: form.llmProvider,
        aiModel: form.aiModel,
        llmApiBase: form.llmApiBase,
        azureDeployment: form.azureDeployment,
        azureApiVersion: form.azureApiVersion,
        googleSheetSyncEnabled: form.googleSheetSyncEnabled,
        googleSheetId: form.googleSheetId,
        googleSheetTab: form.googleSheetTab,
        ...(form.llmApiKey ? { llmApiKey: form.llmApiKey } : {}),
      });
      setInfo("Settings saved.");
      setForm((f) => {
        const next = { ...f, llmApiKey: "", hasLlmApiKey: f.hasLlmApiKey || !!f.llmApiKey };
        setInitialForm(next);
        return next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Site Configuration"
        description="LLM provider, model, and Google Sheet sync configuration."
      />
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-400">{info}</p> : null}

      {loading ? (
        <div className="card space-y-3 p-5">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : (
        <form onSubmit={onSave} className="space-y-4">
          <section className="card p-5">
            <h3 className="text-base font-semibold">LLM</h3>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div>
                <label className="mb-1 block text-sm text-slate-300">Provider</label>
                <select
                  className="input"
                  value={form.llmProvider}
                  onChange={(e) => update("llmProvider", e.target.value)}
                >
                  {providers.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-sm text-slate-300">Model</label>
                <input
                  className="input"
                  value={form.aiModel}
                  onChange={(e) => update("aiModel", e.target.value)}
                  placeholder="e.g. gemini-2.5-flash"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm text-slate-300">API base (optional)</label>
                <input
                  className="input"
                  value={form.llmApiBase}
                  onChange={(e) => update("llmApiBase", e.target.value)}
                  placeholder="https://api.openai.com/v1"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm text-slate-300">
                  API key{" "}
                  {form.hasLlmApiKey ? (
                    <span className="ml-2 rounded bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-300">
                      configured
                    </span>
                  ) : (
                    <span className="ml-2 rounded bg-rose-500/15 px-2 py-0.5 text-xs text-rose-300">missing</span>
                  )}
                </label>
                <input
                  type="password"
                  className="input"
                  value={form.llmApiKey || ""}
                  onChange={(e) => update("llmApiKey", e.target.value)}
                  placeholder={form.hasLlmApiKey ? "•••••••••• (leave blank to keep)" : "Enter API key"}
                />
              </div>
              {form.llmProvider === "azure" && (
                <>
                  <div>
                    <label className="mb-1 block text-sm text-slate-300">Azure deployment</label>
                    <input
                      className="input"
                      value={form.azureDeployment}
                      onChange={(e) => update("azureDeployment", e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-sm text-slate-300">Azure API version</label>
                    <input
                      className="input"
                      value={form.azureApiVersion}
                      onChange={(e) => update("azureApiVersion", e.target.value)}
                    />
                  </div>
                </>
              )}
            </div>
          </section>

          <section className="card p-5">
            <h3 className="text-base font-semibold">Google Sheet sync</h3>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <label className="inline-flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.googleSheetSyncEnabled}
                  onChange={(e) => update("googleSheetSyncEnabled", e.target.checked)}
                />
                Enable automatic Sheet sync
              </label>
              <div />
              <div>
                <label className="mb-1 block text-sm text-slate-300">Sheet URL or ID</label>
                <input
                  className="input"
                  value={form.googleSheetId}
                  onChange={(e) => update("googleSheetId", e.target.value)}
                  placeholder="https://docs.google.com/spreadsheets/d/..."
                />
              </div>
              <div>
                <label className="mb-1 block text-sm text-slate-300">Tab name</label>
                <input
                  className="input"
                  value={form.googleSheetTab}
                  onChange={(e) => update("googleSheetTab", e.target.value)}
                  placeholder="Sheet1"
                />
              </div>
            </div>
          </section>

          {hasChanges ? (
            <div className="flex justify-end">
              <button className="btn-primary" disabled={saving}>
                {saving ? "Saving..." : "Save changes"}
              </button>
            </div>
          ) : null}
        </form>
      )}
    </div>
  );
}
