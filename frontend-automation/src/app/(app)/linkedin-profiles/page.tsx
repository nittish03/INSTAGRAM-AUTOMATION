"use client";

import { useEffect, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { TableSkeleton } from "@/components/skeleton";
import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";
import type { LinkedInProfileItem } from "@/lib/types";

const CACHE_KEY = "linkedin-profiles.list";

type FormState = {
  linkedinUsername: string;
  linkedinPassword: string;
  active: boolean;
  subscribeNewsletter: boolean;
  connectDailyLimit: string;
  connectWeeklyLimit: string;
  followUpDailyLimit: string;
};

const blankForm: FormState = {
  linkedinUsername: "",
  linkedinPassword: "",
  active: true,
  subscribeNewsletter: true,
  connectDailyLimit: "35",
  connectWeeklyLimit: "175",
  followUpDailyLimit: "25",
};

function clampPositive(value: string, fallback: number, max: number): number {
  const n = Number((value ?? "").trim());
  if (!Number.isFinite(n) || n < 1) return fallback;
  return Math.min(Math.floor(n), max);
}

export default function LinkedinProfilesPage() {
  const cached = pageCache.get<LinkedInProfileItem[]>(CACHE_KEY);
  const [items, setItems] = useState<LinkedInProfileItem[]>(cached ?? []);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(!cached);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState<FormState>(blankForm);
  const [formError, setFormError] = useState("");

  async function reload() {
    setError("");
    try {
      const data = await api.linkedinProfiles();
      setItems(data.items);
      pageCache.set(CACHE_KEY, data.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load profiles");
    }
  }

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const data = await api.linkedinProfiles();
        if (!mounted) return;
        setItems(data.items);
        pageCache.set(CACHE_KEY, data.items);
      } catch (e) {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : "Failed to load profiles");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  async function toggle(id: number) {
    setPendingId(id);
    setError("");
    setInfo("");
    try {
      await api.toggleLinkedinProfile(id);
      pageCache.clear(CACHE_KEY);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Toggle failed");
    } finally {
      setPendingId(null);
    }
  }

  async function deleteProfile(p: LinkedInProfileItem) {
    const confirmed = window.confirm(
      `Remove LinkedIn profile "${p.linkedinUsername}"? This unlinks it from your account and clears stored cookies. This cannot be undone.`,
    );
    if (!confirmed) return;
    setDeletingId(p.id);
    setError("");
    setInfo("");
    try {
      await api.deleteLinkedinProfile(p.id);
      pageCache.clear(CACHE_KEY);
      setInfo(`Removed ${p.linkedinUsername}.`);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeletingId(null);
    }
  }

  function openCreate() {
    setForm(blankForm);
    setFormError("");
    setError("");
    setInfo("");
    setCreateOpen(true);
  }

  function closeCreate() {
    if (submitting) return;
    setCreateOpen(false);
  }

  async function submitCreate() {
    const username = form.linkedinUsername.trim();
    const password = form.linkedinPassword;
    if (!username) {
      setFormError("LinkedIn email / username is required.");
      return;
    }
    if (!password) {
      setFormError("LinkedIn password is required.");
      return;
    }
    setSubmitting(true);
    setFormError("");
    try {
      await api.createLinkedinProfile({
        linkedinUsername: username,
        linkedinPassword: password,
        active: form.active,
        subscribeNewsletter: form.subscribeNewsletter,
        connectDailyLimit: clampPositive(form.connectDailyLimit, 35, 500),
        connectWeeklyLimit: clampPositive(form.connectWeeklyLimit, 175, 2000),
        followUpDailyLimit: clampPositive(form.followUpDailyLimit, 25, 500),
      });
      setCreateOpen(false);
      setForm(blankForm);
      pageCache.clear(CACHE_KEY);
      setInfo(`Added ${username}.`);
      await reload();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Failed to add profile");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4">
      <section className="card flex items-start justify-between gap-4 p-5">
        <div>
          <h2 className="text-2xl font-semibold">LinkedIn Profiles</h2>
          <p className="mt-1 text-sm text-slate-400">
            Your LinkedIn accounts. Each is private to your admin login — other
            admins can&apos;t see or run them. Toggle activation, review rate
            limits, or remove any account you no longer want this app to use.
          </p>
        </div>
        <button
          aria-label="Add LinkedIn profile"
          className="btn-primary flex h-10 w-10 shrink-0 items-center justify-center px-0! text-2xl"
          onClick={openCreate}
        >
          +
        </button>
      </section>

      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-400">{info}</p> : null}

      {loading ? (
        <TableSkeleton rows={4} cols={7} />
      ) : items.length === 0 ? (
        <EmptyState
          title="No LinkedIn profiles connected"
          description="Click the + button above to add a LinkedIn account. It will be linked to your admin login only."
        />
      ) : (
        <section className="card overflow-hidden">
          <div className="h-[calc(100vh-15rem)] min-h-88 overflow-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">Operator</th>
                  <th className="th">LinkedIn</th>
                  <th className="th">Active</th>
                  <th className="th">Cookies</th>
                  <th className="th">Connect (D / W)</th>
                  <th className="th">Follow-up (D)</th>
                  <th className="th w-48">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((p) => (
                  <tr key={p.id}>
                    <td className="td">
                      <div>{p.djangoUser}</div>
                      <div className="text-xs text-slate-500">{p.djangoEmail}</div>
                    </td>
                    <td className="td">{p.linkedinUsername}</td>
                    <td className="td">
                      <span
                        className={
                          p.active
                            ? "rounded bg-emerald-500/15 px-2 py-1 text-xs text-emerald-300"
                            : "rounded bg-slate-500/15 px-2 py-1 text-xs text-slate-300"
                        }
                      >
                        {p.active ? "Active" : "Paused"}
                      </span>
                    </td>
                    <td className="td">
                      <span
                        className={
                          p.hasCookies
                            ? "rounded bg-emerald-500/15 px-2 py-1 text-xs text-emerald-300"
                            : "rounded bg-rose-500/15 px-2 py-1 text-xs text-rose-300"
                        }
                      >
                        {p.hasCookies ? "Loaded" : "Missing"}
                      </span>
                    </td>
                    <td className="td">
                      {p.connectDailyLimit} / {p.connectWeeklyLimit}
                    </td>
                    <td className="td">{p.followUpDailyLimit}</td>
                    <td className="td">
                      <div className="flex gap-2">
                        <button
                          onClick={() => toggle(p.id)}
                          disabled={pendingId === p.id || deletingId === p.id}
                          className="btn-secondary disabled:opacity-50"
                        >
                          {pendingId === p.id ? "Saving..." : p.active ? "Pause" : "Activate"}
                        </button>
                        <button
                          onClick={() => deleteProfile(p)}
                          disabled={pendingId === p.id || deletingId === p.id}
                          className="rounded-md bg-rose-500/15 px-3 py-1 text-xs text-rose-200 hover:bg-rose-500/25 disabled:opacity-50"
                        >
                          {deletingId === p.id ? "Removing..." : "Remove"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {createOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4"
          onClick={closeCreate}
        >
          <div
            className="card max-h-[90vh] w-full max-w-xl space-y-4 overflow-y-auto p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold">Add LinkedIn profile</h3>
              <button
                className="text-slate-400 hover:text-slate-200"
                onClick={closeCreate}
                disabled={submitting}
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-slate-400">
              The profile will be linked to your admin login only. You can add
              multiple LinkedIn accounts and switch between them by toggling
              their <em>Active</em> state.
            </p>

            {formError ? (
              <p className="text-sm text-rose-400">{formError}</p>
            ) : null}

            <div className="grid gap-3">
              <div>
                <label className="mb-1 block text-sm text-slate-300">
                  LinkedIn email / username
                </label>
                <input
                  className="input"
                  placeholder="me@example.com"
                  value={form.linkedinUsername}
                  autoFocus
                  onChange={(e) =>
                    setForm((f) => ({ ...f, linkedinUsername: e.target.value }))
                  }
                />
              </div>

              <div>
                <label className="mb-1 block text-sm text-slate-300">
                  LinkedIn password
                </label>
                <input
                  className="input"
                  type="password"
                  placeholder="••••••••"
                  value={form.linkedinPassword}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, linkedinPassword: e.target.value }))
                  }
                />
                <p className="mt-1 text-xs text-slate-500">
                  Encrypted at rest. Used by the daemon to log in via Playwright.
                </p>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <div>
                  <label className="mb-1 block text-sm text-slate-300">
                    Connect / day
                  </label>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    max={500}
                    value={form.connectDailyLimit}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        connectDailyLimit: e.target.value,
                      }))
                    }
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm text-slate-300">
                    Connect / week
                  </label>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    max={2000}
                    value={form.connectWeeklyLimit}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        connectWeeklyLimit: e.target.value,
                      }))
                    }
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm text-slate-300">
                    Follow-up / day
                  </label>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    max={500}
                    value={form.followUpDailyLimit}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        followUpDailyLimit: e.target.value,
                      }))
                    }
                  />
                </div>
              </div>

              <div className="flex flex-wrap gap-4">
                <label className="inline-flex items-center gap-2 text-sm text-slate-300">
                  <input
                    type="checkbox"
                    checked={form.active}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, active: e.target.checked }))
                    }
                  />
                  Active immediately
                </label>
                <label className="inline-flex items-center gap-2 text-sm text-slate-300">
                  <input
                    type="checkbox"
                    checked={form.subscribeNewsletter}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        subscribeNewsletter: e.target.checked,
                      }))
                    }
                  />
                  Subscribe to newsletter on first login
                </label>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                className="btn-secondary"
                onClick={closeCreate}
                disabled={submitting}
              >
                Cancel
              </button>
              <button
                className="btn-primary"
                onClick={submitCreate}
                disabled={
                  submitting ||
                  !form.linkedinUsername.trim() ||
                  !form.linkedinPassword
                }
              >
                {submitting ? "Adding..." : "Add profile"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
