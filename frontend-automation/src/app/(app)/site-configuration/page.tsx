"use client";

import { FormEvent, useEffect, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Skeleton } from "@/components/skeleton";
import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";
import type { LlmModelOption, SiteConfig } from "@/lib/types";

type FormState = SiteConfig & { llmApiKey?: string };

type ChatMessage = { role: "user" | "assistant"; content: string };

const CONFIG_KEY = "site-configuration.config";
const PROVIDERS_KEY = "site-configuration.providers";

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
  const cachedConfig = pageCache.get<FormState>(CONFIG_KEY);
  const cachedProviders = pageCache.get<{ value: string; label: string }[]>(PROVIDERS_KEY);
  const [form, setForm] = useState<FormState>(cachedConfig ?? blank);
  const [initialForm, setInitialForm] = useState<FormState>(cachedConfig ?? blank);
  const [providers, setProviders] = useState<{ value: string; label: string }[]>(
    cachedProviders ?? [],
  );
  const [loading, setLoading] = useState(!cachedConfig);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState("");
  const [modelOptions, setModelOptions] = useState<LlmModelOption[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState("");
  const [modelsHint, setModelsHint] = useState("");
  const [modelsFilteredOut, setModelsFilteredOut] = useState(0);
  const [modelsSource, setModelsSource] = useState("");

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const res = await api.siteConfig();
        if (!mounted) return;
        const loaded = { ...res.config, llmApiKey: "" };
        setForm(loaded);
        setInitialForm(loaded);
        setProviders(res.providerChoices);
        pageCache.set(CONFIG_KEY, loaded);
        pageCache.set(PROVIDERS_KEY, res.providerChoices);
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

  function llmConfigPayload() {
    return {
      llmProvider: form.llmProvider,
      aiModel: form.aiModel,
      llmApiBase: form.llmApiBase,
      azureDeployment: form.azureDeployment,
      azureApiVersion: form.azureApiVersion,
      ...(form.llmApiKey ? { llmApiKey: form.llmApiKey } : {}),
    };
  }

  async function onFetchModels() {
    setModelsLoading(true);
    setModelsError("");
    setModelsHint("");
    setModelsFilteredOut(0);
    setModelsSource("");
    try {
      const res = await api.listLlmModels(llmConfigPayload());
      if (!res.ok) {
        throw new Error(res.error || "Failed to fetch models");
      }
      setModelOptions(res.models);
      setModelsHint(res.hint);
      setModelsFilteredOut(res.filteredOut);
      setModelsSource(res.source);
      if (res.models.length === 0) {
        setModelsError("No models returned for this provider/key.");
      }
    } catch (e) {
      setModelOptions([]);
      setModelsError(e instanceof Error ? e.message : "Failed to fetch models");
    } finally {
      setModelsLoading(false);
    }
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
        pageCache.set(CONFIG_KEY, next);
        return next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function onSendChat() {
    const message = chatInput.trim();
    if (!message || chatLoading) return;

    setChatInput("");
    setChatError("");
    setChatMessages((prev) => [...prev, { role: "user", content: message }]);
    setChatLoading(true);

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 25_000);

    try {
      const res = await api.llmChat(
        {
          message,
          ...llmConfigPayload(),
        },
        { signal: controller.signal },
      );
      if (!res.ok) {
        throw new Error(res.error || "LLM request failed");
      }
      setChatMessages((prev) => [...prev, { role: "assistant", content: res.reply }]);
    } catch (e) {
      const msg =
        e instanceof Error && e.name === "AbortError"
          ? "Request timed out after 25s. The API may be retrying quota errors — try gemini-2.5-flash or check billing."
          : e instanceof Error
            ? e.message
            : "LLM request failed";
      setChatError(msg);
      setChatMessages((prev) => [...prev, { role: "assistant", content: `Error: ${msg}` }]);
    } finally {
      window.clearTimeout(timeoutId);
      setChatLoading(false);
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
                  onChange={(e) => {
                    update("llmProvider", e.target.value);
                    setModelOptions([]);
                    setModelsError("");
                    setModelsHint("");
                    setModelsFilteredOut(0);
                    setModelsSource("");
                  }}
                >
                  {providers.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </select>
                {form.llmProvider === "gemini" ? (
                  <p className="mt-1 text-xs text-slate-500">Use a Google Gemini key. No base URL required.</p>
                ) : null}
              </div>
              <div className="md:col-span-2">
                <div className="mb-1 flex items-center justify-between gap-3">
                  <label className="block text-sm text-slate-300">Model (optional)</label>
                  <button
                    type="button"
                    className="text-xs text-sky-400 hover:text-sky-300 disabled:opacity-50"
                    disabled={modelsLoading || (!form.hasLlmApiKey && !form.llmApiKey?.trim())}
                    onClick={() => void onFetchModels()}
                  >
                    {modelsLoading ? "Fetching…" : "Fetch models"}
                  </button>
                </div>
                <input
                  className="input"
                  value={form.aiModel}
                  onChange={(e) => update("aiModel", e.target.value)}
                  placeholder={
                    form.llmProvider === "gemini" ? "e.g. gemini-2.5-flash (blank uses default)" : "e.g. gpt-4o-mini"
                  }
                />
                {modelOptions.length > 0 ? (
                  <select
                    className="input mt-2"
                    value={form.aiModel}
                    onChange={(e) => update("aiModel", e.target.value)}
                  >
                    <option value="">— select a fetched model —</option>
                    {modelOptions.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                ) : null}
                {modelsHint ? (
                  <p className="mt-1 text-xs text-slate-500">
                    {modelsHint}
                    {modelsSource ? ` ${modelOptions.length} found via ${modelsSource}.` : ""}
                  </p>
                ) : null}
                {modelsFilteredOut > 0 ? (
                  <p className="mt-1 text-xs text-amber-400/90">
                    Filtered out {modelsFilteredOut} unavailable or non-chat model
                    {modelsFilteredOut === 1 ? "" : "s"}.
                  </p>
                ) : null}
                {modelsError ? <p className="mt-1 text-xs text-rose-400">{modelsError}</p> : null}
              </div>
              <div>
                <label className="mb-1 block text-sm text-slate-300">
                  API base {form.llmProvider === "gemini" ? "(not used for Gemini)" : "(optional)"}
                </label>
                <input
                  className="input"
                  value={form.llmApiBase}
                  onChange={(e) => update("llmApiBase", e.target.value)}
                  placeholder={
                    form.llmProvider === "azure"
                      ? "https://your-resource.openai.azure.com"
                      : "https://api.openai.com/v1"
                  }
                  disabled={form.llmProvider === "gemini"}
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

            <div className="mt-6 border-t border-slate-700/60 pt-5">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h4 className="text-sm font-semibold text-slate-100">Test LLM connection</h4>
                  <p className="mt-1 text-xs text-slate-400">
                    Send a message to verify the API. Uses the values above (including unsaved changes).
                    {form.llmProvider === "gemini" ? (
                      <span className="mt-1 block text-amber-400/90">
                        Gemini Pro often has no free-tier quota — use gemini-2.5-flash for testing.
                      </span>
                    ) : null}
                  </p>
                </div>
                {chatMessages.length > 0 ? (
                  <button
                    type="button"
                    className="text-xs text-slate-400 hover:text-slate-200"
                    onClick={() => {
                      setChatMessages([]);
                      setChatError("");
                    }}
                  >
                    Clear
                  </button>
                ) : null}
              </div>

              <div className="mt-3 max-h-48 space-y-2 overflow-y-auto rounded-lg border border-slate-700/60 bg-slate-950/40 p-3">
                {chatMessages.length === 0 ? (
                  <p className="text-xs text-slate-500">No messages yet. Try &quot;Reply with OK&quot;.</p>
                ) : (
                  chatMessages.map((msg, i) => (
                    <div
                      key={i}
                      className={`rounded-md px-3 py-2 text-sm ${
                        msg.role === "user"
                          ? "ml-8 bg-sky-500/15 text-sky-100"
                          : "mr-8 bg-slate-800/80 text-slate-200"
                      }`}
                    >
                      <span className="mb-1 block text-[10px] uppercase tracking-wide text-slate-400">
                        {msg.role === "user" ? "You" : "LLM"}
                      </span>
                      <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                    </div>
                  ))
                )}
                {chatLoading ? (
                  <p className="text-xs text-slate-400">Waiting for response...</p>
                ) : null}
              </div>

              {chatError ? <p className="mt-2 text-xs text-rose-400">{chatError}</p> : null}

              <div className="mt-3 flex gap-2">
                <input
                  className="input flex-1"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void onSendChat();
                    }
                  }}
                  placeholder="Type a test message..."
                  disabled={chatLoading}
                />
                <button
                  type="button"
                  className="btn-primary shrink-0 px-4"
                  disabled={chatLoading || !chatInput.trim()}
                  onClick={() => void onSendChat()}
                >
                  {chatLoading ? "Sending..." : "Send"}
                </button>
              </div>
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
