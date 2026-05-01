"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";
import { TableSkeleton } from "@/components/skeleton";
import type { DraftMessage, MessagingDiagnostics } from "@/lib/types";

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
  const [diag, setDiag] = useState<MessagingDiagnostics | null>(cachedDiag ?? null);
  const [healing, setHealing] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingContent, setEditingContent] = useState("");
  const [savingId, setSavingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [bulkDeleting, setBulkDeleting] = useState(false);

  async function load() {
    try {
      const [drafts, d] = await Promise.all([api.drafts(), api.messagingDiagnostics()]);
      setItems(drafts.items);
      setSelected({});
      setDiag(d.diagnostics);
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
        const [drafts, d] = await Promise.all([api.drafts(), api.messagingDiagnostics()]);
        if (!mounted) return;
        setItems(drafts.items);
        setDiag(d.diagnostics);
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
  const allSelected = items.length > 0 && items.every((m) => !!selected[m.id]);

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
    for (const m of items) next[m.id] = true;
    setSelected(next);
  }

  function startEdit(d: DraftMessage) {
    setEditingId(d.id);
    setEditingContent(d.content);
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
        const next = cur.map((m) => (m.id === id ? { ...m, content: r.item.content } : m));
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
    if (!confirm(`Delete ${ids.length} selected draft(s)? This cannot be undone.`)) return;
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
      setError(e instanceof Error ? e.message : "Failed to delete selected drafts");
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
        <h2 className="text-2xl font-semibold">Draft Messages (HITL)</h2>
        <p className="mt-1 text-sm text-slate-400">
          Select drafts and approve to queue <code>send_message</code> tasks.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button disabled={!ids.length || loading} className="btn-primary" onClick={approve}>
            {loading ? "Approving..." : `Approve Selected (${ids.length})`}
          </button>
          <button
            disabled={initialLoading || items.length === 0 || loading || bulkDeleting}
            className="btn-secondary"
            onClick={toggleSelectAll}
          >
            {allSelected ? "Clear Selection" : "Select All"}
          </button>
          <button
            disabled={!ids.length || loading || bulkDeleting}
            className="btn-secondary text-rose-300 hover:text-rose-200"
            onClick={deleteSelectedDrafts}
          >
            {bulkDeleting ? "Deleting..." : `Delete Selected (${ids.length})`}
          </button>
          <button disabled={healing} className="btn-secondary" onClick={healFollowups}>
            {healing ? "Queuing..." : "Re-queue follow-ups for connected leads"}
          </button>
        </div>
      </section>

      {diag ? (
        <section className="card p-5">
          <h3 className="text-lg font-semibold">Messaging diagnostics</h3>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="Connected deals" value={diag.connectedDeals} />
            <Stat label="Drafts (total)" value={diag.draftsTotal} />
            <Stat label="Awaiting approval" value={diag.draftsUnapproved} />
            <Stat label="Pending follow-up tasks" value={diag.pendingFollowupTasks} />
            <Stat label="Failed follow-up tasks" value={diag.failedFollowupTasks} tone={diag.failedFollowupTasks ? "warn" : undefined} />
            <Stat label="Pending sends" value={diag.pendingSendMessageTasks} />
          </div>

          {llmMissing ? (
            <p className="mt-4 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
              LLM is not configured (missing API key or model). Drafts cannot be generated until you set this in
              Site Configuration.
            </p>
          ) : null}

          {noDrafts && hasOrphans ? (
            <p className="mt-4 text-sm text-slate-400">
              {diag.leadsWithoutDraft.length} connected lead(s) currently have no draft and no queued follow-up.
              Click <em>Re-queue follow-ups</em> above; the daemon will pick them up on its next idle pass.
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
          No drafts awaiting approval yet. Once the daemon processes a follow-up task, drafts will appear here.
        </section>
      ) : (
        <section className="card overflow-hidden">
          <div className="h-[calc(100vh-15rem)] min-h-88 overflow-auto">
            <table className="w-full">
            <thead>
              <tr>
                <th className="th w-10">#</th>
                <th className="th">Lead</th>
                <th className="th">Campaign</th>
                <th className="th">Message</th>
                <th className="th">Created</th>
                <th className="th w-44">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((m) => {
                const isEditing = editingId === m.id;
                const isSaving = savingId === m.id;
                const isDeleting = deletingId === m.id;
                return (
                  <tr key={m.id}>
                    <td className="td align-top">
                      <input
                        type="checkbox"
                        checked={!!selected[m.id]}
                        disabled={isEditing}
                        onChange={(e) =>
                          setSelected((s) => ({ ...s, [m.id]: e.target.checked }))
                        }
                      />
                    </td>
                    <td className="td align-top">
                      <div>{m.leadName || "-"}</div>
                      <div className="text-xs text-slate-500">{m.leadPublicIdentifier}</div>
                    </td>
                    <td className="td align-top">{m.campaign || "-"}</td>
                    <td className="td align-top">
                      {isEditing ? (
                        <textarea
                          className="input min-h-[100px] w-full"
                          value={editingContent}
                          onChange={(e) => setEditingContent(e.target.value)}
                          autoFocus
                        />
                      ) : (
                        <span className="whitespace-pre-wrap">{m.content}</span>
                      )}
                    </td>
                    <td className="td align-top">{new Date(m.createdAt).toLocaleString()}</td>
                    <td className="td align-top">
                      {isEditing ? (
                        <div className="flex flex-wrap gap-2">
                          <button
                            className="btn-primary"
                            disabled={isSaving}
                            onClick={() => saveEdit(m.id)}
                          >
                            {isSaving ? "Saving..." : "Save"}
                          </button>
                          <button
                            className="btn-secondary"
                            disabled={isSaving}
                            onClick={cancelEdit}
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <div className="flex flex-wrap gap-2">
                          <button
                            className="btn-secondary"
                            onClick={() => startEdit(m)}
                            disabled={isDeleting}
                          >
                            Edit
                          </button>
                          <button
                            className="btn-secondary text-rose-300 hover:text-rose-200"
                            onClick={() => deleteDraft(m.id)}
                            disabled={isDeleting}
                          >
                            {isDeleting ? "Deleting..." : "Delete"}
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
              </table>
            </div>
        </section>
      )}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "warn" }) {
  return (
    <div className={`rounded-lg border border-slate-800 bg-slate-900/40 p-3 ${tone === "warn" ? "border-amber-500/40" : ""}`}>
      <div className="text-xs uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${tone === "warn" ? "text-amber-300" : "text-slate-100"}`}>
        {value.toLocaleString()}
      </div>
    </div>
  );
}
