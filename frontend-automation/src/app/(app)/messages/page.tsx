"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";
import { TableSkeleton } from "@/components/skeleton";
import type {
  DraftMessage,
  FollowupSuggestion,
  MessagingDiagnostics,
} from "@/lib/types";

const DRAFTS_KEY = "messages.drafts";
const DIAG_KEY = "messages.diagnostics";

export default function MessagesPage() {
  const cachedDrafts = pageCache.get<DraftMessage[]>(DRAFTS_KEY);
  const cachedDiag = pageCache.get<MessagingDiagnostics>(DIAG_KEY);
  const [items, setItems] = useState<DraftMessage[]>(cachedDrafts ?? []);
  const [selected, setSelected] = useState<Record<number, boolean>>({});
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(!cachedDrafts);
  const [diag, setDiag] = useState<MessagingDiagnostics | null>(
    cachedDiag ?? null,
  );
  const [healing, setHealing] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingContent, setEditingContent] = useState("");
  const [savingId, setSavingId] = useState<number | null>(null);
  const [regeneratingId, setRegeneratingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [suggestions, setSuggestions] = useState<FollowupSuggestion[]>([]);

  async function load() {
    try {
      const [drafts, d, s] = await Promise.all([
        api.drafts(),
        api.messagingDiagnostics(),
        api.followupSuggestions(50),
      ]);
      setItems(drafts.items);
      setSelected({});
      setDiag(d.diagnostics);
      setSuggestions(s.items);
      pageCache.set(DRAFTS_KEY, drafts.items);
      pageCache.set(DIAG_KEY, d.diagnostics);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load drafts");
    } finally {
      setInitialLoading(false);
    }
  }

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const [drafts, d, s] = await Promise.all([
          api.drafts(),
          api.messagingDiagnostics(),
          api.followupSuggestions(50),
        ]);
        if (!mounted) return;
        setItems(drafts.items);
        setDiag(d.diagnostics);
        setSuggestions(s.items);
        setSelected({});
        pageCache.set(DRAFTS_KEY, drafts.items);
        pageCache.set(DIAG_KEY, d.diagnostics);
      } catch (e) {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : "Failed to load drafts");
      } finally {
        if (mounted) setInitialLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  const ids = Object.entries(selected)
    .filter(([, v]) => v)
    .map(([k]) => Number(k));
  const selectedIncludesRegenerating =
    regeneratingId !== null && ids.includes(regeneratingId);
  const selectedIncludesEditing = editingId !== null && ids.includes(editingId);
  const selectableItems = items.filter(
    (m) => m.id !== editingId && m.id !== regeneratingId,
  );
  const allSelected =
    selectableItems.length > 0 &&
    selectableItems.every((m) => !!selected[m.id]);

  async function approve() {
    if (!ids.length) return;
    setLoading(true);
    setError("");
    setInfo("");
    try {
      const data = await api.approveDrafts(ids);
      setInfo(`Approved ${data.approved} draft(s).`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setLoading(false);
    }
  }

  function toggleSelectAll() {
    if (allSelected) {
      setSelected({});
      return;
    }
    const next: Record<number, boolean> = {};
    for (const m of items) {
      if (m.id !== editingId && m.id !== regeneratingId) next[m.id] = true;
    }
    setSelected(next);
  }

  function startEdit(d: DraftMessage) {
    setEditingId(d.id);
    setEditingContent(d.content);
    setSelected((s) => ({ ...s, [d.id]: false }));
    setError("");
    setInfo("");
  }

  function cancelEdit() {
    setEditingId(null);
    setEditingContent("");
  }

  async function saveEdit(id: number) {
    const content = editingContent.trim();
    if (!content) {
      setError("Draft content cannot be empty.");
      return;
    }
    setSavingId(id);
    setError("");
    try {
      const r = await api.updateDraft(id, content);
      setItems((cur) => {
        const next = cur.map((m) =>
          m.id === id ? { ...m, content: r.item.content } : m,
        );
        pageCache.set(DRAFTS_KEY, next);
        return next;
      });
      setEditingId(null);
      setEditingContent("");
      setInfo("Draft updated.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save draft");
    } finally {
      setSavingId(null);
    }
  }

  async function regenerateDraft(id: number) {
    if (
      !confirm(
        "Regenerate this draft? The current draft text will be replaced, but nothing will be sent.",
      )
    )
      return;
    setRegeneratingId(id);
    setError("");
    setInfo("");
    try {
      const r = await api.regenerateDraft(id);
      setItems((cur) => {
        const next = cur.map((m) =>
          m.id === id
            ? {
                ...m,
                content: r.item.content,
                latestMessage:
                  "latestMessage" in r.item
                    ? (r.item.latestMessage ?? null)
                    : m.latestMessage,
              }
            : m,
        );
        pageCache.set(DRAFTS_KEY, next);
        return next;
      });
      if (editingId === id) {
        setEditingContent(r.item.content);
      }
      const suffix = r.changed
        ? "Draft regenerated."
        : `Draft unchanged (${r.status}).`;
      setInfo(r.reason ? `${suffix} ${r.reason}` : suffix);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to regenerate draft");
    } finally {
      setRegeneratingId(null);
    }
  }

  async function deleteDraft(id: number) {
    if (!confirm("Delete this draft? This cannot be undone.")) return;
    setDeletingId(id);
    setError("");
    setInfo("");
    try {
      await api.deleteDraft(id);
      setItems((cur) => {
        const next = cur.filter((m) => m.id !== id);
        pageCache.set(DRAFTS_KEY, next);
        return next;
      });
      setSelected((s) => {
        const next = { ...s };
        delete next[id];
        return next;
      });
      if (editingId === id) cancelEdit();
      setInfo("Draft deleted.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete draft");
    } finally {
      setDeletingId(null);
    }
  }

  async function deleteSelectedDrafts() {
    if (!ids.length) return;
    if (
      !confirm(`Delete ${ids.length} selected draft(s)? This cannot be undone.`)
    )
      return;
    setBulkDeleting(true);
    setError("");
    setInfo("");
    try {
      await Promise.all(ids.map((id) => api.deleteDraft(id)));
      setItems((cur) => {
        const idSet = new Set(ids);
        const next = cur.filter((m) => !idSet.has(m.id));
        pageCache.set(DRAFTS_KEY, next);
        return next;
      });
      if (editingId && ids.includes(editingId)) cancelEdit();
      setSelected({});
      setInfo(`Deleted ${ids.length} draft(s).`);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Failed to delete selected drafts",
      );
    } finally {
      setBulkDeleting(false);
    }
  }

  async function healFollowups() {
    setHealing(true);
    setError("");
    setInfo("");
    try {
      const r = await api.messagingHeal();
      setInfo(
        `Queued ${r.enqueued} follow_up task(s); skipped ${r.skipped} already drafted/queued. ` +
          `Drafts will appear once the daemon processes the queue.`,
      );
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Heal failed");
    } finally {
      setHealing(false);
    }
  }

  const llmMissing = diag && !diag.llmConfigured;
  const noDrafts = diag && diag.draftsUnapproved === 0;
  const hasOrphans = diag && diag.leadsWithoutDraft.length > 0;

  return (
    <div className="space-y-4">
      <section className="card p-5">
        <h2 className="text-2xl font-semibold">Instagram DM Drafts (HITL)</h2>
        <p className="mt-1 text-sm text-slate-400">
          Review AI-generated Instagram DMs (Eshway website clients + agency
          collabs), then approve to queue <code>send_message</code> tasks for the
          Instagram worker daemon. Edit or regenerate before approving — approval
          still runs the automated send pipeline.
        </p>
        <p className="mt-2 text-xs text-slate-500">
          Drafts should stay short and personalized (CLIENT / COLLABORATION /
          BOTH). Prefer one strong profile detail, a clear Eshway relevance line,
          and a low-pressure CTA — not a full pitch.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            disabled={
              !ids.length ||
              loading ||
              selectedIncludesRegenerating ||
              selectedIncludesEditing
            }
            className="btn-primary"
            onClick={approve}
          >
            {loading ? "Approving..." : `Approve Selected (${ids.length})`}
          </button>
          <button
            disabled={
              initialLoading || items.length === 0 || loading || bulkDeleting
            }
            className="btn-secondary"
            onClick={toggleSelectAll}
          >
            {allSelected ? "Clear Selection" : "Select All"}
          </button>
          <button
            disabled={
              !ids.length ||
              loading ||
              bulkDeleting ||
              selectedIncludesRegenerating ||
              selectedIncludesEditing
            }
            className="btn-secondary text-rose-300 hover:text-rose-200"
            onClick={deleteSelectedDrafts}
          >
            {bulkDeleting ? "Deleting..." : `Delete Selected (${ids.length})`}
          </button>
          <button
            disabled={healing}
            className="btn-secondary"
            onClick={healFollowups}
          >
            {healing ? "Queuing..." : "Re-queue drafts for qualified leads"}
          </button>
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs text-slate-400">
          <span>{suggestions.length} follow-up suggestion(s) available.</span>
          <a
            className="text-violet-300 hover:underline"
            href="/follow-up-suggestions"
          >
            Open suggestions
          </a>
        </div>
      </section>

      {diag ? (
        <section className="card p-5">
          <h3 className="text-lg font-semibold">Messaging diagnostics</h3>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="Qualified deals" value={diag.qualifiedDeals ?? 0} />
            <Stat label="Connected deals" value={diag.connectedDeals} />
            <Stat label="Drafts (total)" value={diag.draftsTotal} />
            <Stat label="Awaiting approval" value={diag.draftsUnapproved} />
            <Stat
              label="Pending follow-up tasks"
              value={diag.pendingFollowupTasks}
            />
            <Stat
              label="Failed follow-up tasks"
              value={diag.failedFollowupTasks}
              tone={diag.failedFollowupTasks ? "warn" : undefined}
            />
            <Stat label="Pending sends" value={diag.pendingSendMessageTasks} />
          </div>

          {llmMissing ? (
            <p className="mt-4 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
              LLM is not configured (missing API key or model). Drafts cannot be
              generated until you set this in Site Configuration.
            </p>
          ) : null}

          {noDrafts && hasOrphans ? (
            <p className="mt-4 text-sm text-slate-400">
              {diag.leadsWithoutDraft.length} qualified/connected lead(s) currently have
              no draft and no queued follow-up. Click{" "}
              <em>Re-queue drafts</em> above; the daemon will pick them up
              on its next idle pass.
            </p>
          ) : null}

          {diag.lastFailedFollowup ? (
            <details className="mt-4">
              <summary className="cursor-pointer text-sm text-slate-300">
                Last failed follow-up — task #{diag.lastFailedFollowup.taskId}
                {diag.lastFailedFollowup.endedAt
                  ? ` at ${new Date(diag.lastFailedFollowup.endedAt).toLocaleString()}`
                  : null}
              </summary>
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-md bg-slate-950/60 p-3 text-xs text-rose-300">
                {diag.lastFailedFollowup.error || "(no error captured)"}
              </pre>
            </details>
          ) : null}
        </section>
      ) : null}

      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-400">{info}</p> : null}
      {initialLoading ? (
        <TableSkeleton rows={6} cols={5} />
      ) : items.length === 0 ? (
        <section className="card p-8 text-center text-sm text-slate-400">
          No drafts awaiting approval yet. Once a lead is Qualified, the Instagram
          worker creates a DM draft here for HITL review (no follow required).
        </section>
      ) : (
        <section className="space-y-3">
          {items.map((m) => {
            const isEditing = editingId === m.id;
            const isSaving = savingId === m.id;
            const isRegenerating = regeneratingId === m.id;
            const isDeleting = deletingId === m.id;
            const leadLabel = m.leadName || m.leadPublicIdentifier || "lead";
            return (
              <article
                key={m.id}
                className="card overflow-hidden border-slate-800/80"
              >
                <div className="flex flex-col gap-4 p-5 lg:flex-row lg:items-start lg:justify-between">
                  <div className="flex min-w-0 items-start gap-3">
                    <input
                      className="mt-1"
                      type="checkbox"
                      checked={!!selected[m.id]}
                      disabled={isEditing || isRegenerating}
                      onChange={(e) =>
                        setSelected((s) => ({ ...s, [m.id]: e.target.checked }))
                      }
                      aria-label={`Select draft for ${m.leadName || m.leadPublicIdentifier || "lead"}`}
                    />
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="truncate text-base font-semibold text-slate-100">
                          {m.leadName ||
                            m.leadPublicIdentifier ||
                            "Unknown lead"}
                        </h3>
                        {m.campaign ? (
                          <span className="rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 text-[11px] uppercase tracking-wide text-slate-400">
                            {m.campaign}
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-1 text-xs text-slate-500">
                        {m.leadPublicIdentifier || "No public id"}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        Drafted {formatDateTime(m.createdAt)}
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                    {isEditing ? (
                      <>
                        <button
                          className="btn-primary"
                          disabled={isSaving}
                          aria-label={`Save draft for ${leadLabel}`}
                          onClick={() => saveEdit(m.id)}
                        >
                          {isSaving ? "Saving..." : "Save draft"}
                        </button>
                        <button
                          className="btn-secondary"
                          disabled={isSaving}
                          aria-label={`Cancel editing draft for ${leadLabel}`}
                          onClick={cancelEdit}
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          className="btn-secondary"
                          onClick={() => startEdit(m)}
                          disabled={isDeleting || isRegenerating}
                          aria-label={`Edit draft for ${leadLabel}`}
                        >
                          Edit
                        </button>
                        <button
                          className="btn-secondary text-violet-200 hover:text-violet-100"
                          onClick={() => regenerateDraft(m.id)}
                          disabled={isDeleting || isRegenerating}
                          aria-label={`Regenerate draft for ${leadLabel}`}
                        >
                          {isRegenerating ? "Regenerating..." : "Regenerate"}
                        </button>
                        <button
                          className="btn-secondary text-rose-300 hover:text-rose-200"
                          onClick={() => deleteDraft(m.id)}
                          disabled={isDeleting || isRegenerating}
                          aria-label={`Delete draft for ${leadLabel}`}
                        >
                          {isDeleting ? "Deleting..." : "Delete"}
                        </button>
                      </>
                    )}
                  </div>
                </div>

                <div className="grid gap-4 border-t border-slate-800 bg-slate-950/20 p-5 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
                  <section className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                        Last synced Instagram message
                      </h4>
                      {m.latestMessage ? (
                        <span
                          className={
                            m.latestMessage.isOutgoing
                              ? "text-xs text-sky-300"
                              : "text-xs text-emerald-300"
                          }
                        >
                          {m.latestMessage.senderLabel} •{" "}
                          {formatDateTime(m.latestMessage.createdAt)}
                        </span>
                      ) : null}
                    </div>
                    {m.latestMessage ? (
                      <p className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap text-sm leading-relaxed text-slate-200">
                        {m.latestMessage.content}
                      </p>
                    ) : (
                      <p className="mt-3 text-sm text-slate-500">
                        No synced Instagram DMs found yet. Run the Instagram
                        worker daemon or sync this conversation before approving.
                      </p>
                    )}
                  </section>

                  <section className="rounded-xl border border-violet-500/20 bg-violet-500/5 p-4">
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-violet-300">
                      Draft awaiting approval
                    </h4>
                    {isEditing ? (
                      <textarea
                        className="input mt-3 min-h-[150px] w-full"
                        aria-label={`Draft text for ${leadLabel}`}
                        value={editingContent}
                        onChange={(e) => setEditingContent(e.target.value)}
                        autoFocus
                      />
                    ) : (
                      <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-slate-100">
                        {m.content}
                      </p>
                    )}
                  </section>
                </div>
              </article>
            );
          })}
        </section>
      )}
    </div>
  );
}

function formatDateTime(value: string) {
  if (!value) return "";
  return new Date(value).toLocaleString();
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "warn";
}) {
  return (
    <div
      className={`rounded-lg border border-slate-800 bg-slate-900/40 p-3 ${tone === "warn" ? "border-amber-500/40" : ""}`}
    >
      <div className="text-xs uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div
        className={`mt-1 text-2xl font-semibold ${tone === "warn" ? "text-amber-300" : "text-slate-100"}`}
      >
        {value.toLocaleString()}
      </div>
    </div>
  );
}
