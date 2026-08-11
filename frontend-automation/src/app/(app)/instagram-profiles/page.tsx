"use client";

import { useEffect, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { TableSkeleton } from "@/components/skeleton";
import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";
import type { InstagramProfileItem } from "@/lib/types";

const CACHE_KEY = "instagram-profiles.list";

type FormState = {
  username: string;
  password: string;
  active: boolean;
  dmDailyLimit: string;
};

const blankForm: FormState = {
  username: "",
  password: "",
  active: true,
  // Conservative Instagram DM default.
  dmDailyLimit: "15",
};

function clampPositive(value: string, fallback: number, max: number): number {
  const n = Number((value ?? "").trim());
  if (!Number.isFinite(n) || n < 1) return fallback;
  return Math.min(Math.floor(n), max);
}

export default function InstagramProfilesPage() {
  const cached = pageCache.get<InstagramProfileItem[]>(CACHE_KEY);
  const [items, setItems] = useState<InstagramProfileItem[]>(cached ?? []);
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
      const data = await api.instagramProfiles();
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
        const data = await api.instagramProfiles();
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
      await api.toggleInstagramProfile(id);
      pageCache.clear(CACHE_KEY);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Toggle failed");
    } finally {
      setPendingId(null);
    }
  }

  async function deleteProfile(p: InstagramProfileItem) {
    const confirmed = window.confirm(
      `Remove Instagram profile "@${p.username}"? This unlinks it from your account and clears stored session cookies. This cannot be undone.`,
    );
    if (!confirmed) return;
    setDeletingId(p.id);
    setError("");
    setInfo("");
    try {
      await api.deleteInstagramProfile(p.id);
      pageCache.clear(CACHE_KEY);
      setInfo(`Removed @${p.username}.`);
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
    const username = form.username.trim().replace(/^@/, "");
    const password = form.password;
    if (!username) {
      setFormError("Instagram username is required.");
      return;
    }
    if (!password) {
      setFormError("Instagram password is required.");
      return;
    }
    setSubmitting(true);
    setFormError("");
    try {
      await api.createInstagramProfile({
        username,
        password,
        active: form.active,
        dmDailyLimit: clampPositive(form.dmDailyLimit, 15, 200),
      });
      setCreateOpen(false);
      setForm(blankForm);
      pageCache.clear(CACHE_KEY);
      setInfo(`Added @${username}.`);
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
          <h2 className="text-2xl font-semibold">Instagram Profiles</h2>
          <p className="mt-1 text-sm text-slate-400">
            Operator Instagram accounts for the automation loop (discover → qualify →
            DM). Each account is private to your admin login — other admins can&apos;t
            see or run them. Toggle activation, review DM rate limits, or remove any
            account you no longer want this app to use.
          </p>
        </div>
        <button
          aria-label="Add Instagram profile"
          className="btn-primary flex h-10 w-10 shrink-0 items-center justify-center px-0! text-2xl"
          onClick={openCreate}
        >
          +
        </button>
      </section>

      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-400">{info}</p> : null}

      {loading ? (
        <TableSkeleton rows={4} cols={6} />
      ) : items.length === 0 ? (
        <EmptyState
          title="No Instagram profiles connected"
          description="Click the + button above to add an Instagram account. The daemon uses it for discovery and DMs — linked to your admin login only."
        />
      ) : (
        <section className="card overflow-hidden">
          <div className="h-[calc(100vh-15rem)] min-h-88 overflow-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">Operator</th>
                  <th className="th">Instagram</th>
                  <th className="th">Active</th>
                  <th className="th">Session</th>
                  <th className="th">DM / day</th>
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
                    <td className="td">@{p.username}</td>
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
                    <td className="td">{p.dmDailyLimit}</td>
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
              <h3 className="text-lg font-semibold">Add Instagram profile</h3>
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
              multiple Instagram accounts and switch between them by toggling
              their <em>Active</em> state. Keep the DM / day limit conservative to
              reduce account risk.
            </p>

            {formError ? (
              <p className="text-sm text-rose-400">{formError}</p>
            ) : null}

            <div className="grid gap-3">
              <div>
                <label className="mb-1 block text-sm text-slate-300">
                  Instagram username
                </label>
                <input
                  className="input"
                  placeholder="eshway"
                  value={form.username}
                  autoFocus
                  onChange={(e) =>
                    setForm((f) => ({ ...f, username: e.target.value }))
                  }
                />
              </div>

              <div>
                <label className="mb-1 block text-sm text-slate-300">
                  Instagram password
                </label>
                <input
                  className="input"
                  type="password"
                  placeholder="••••••••"
                  value={form.password}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, password: e.target.value }))
                  }
                />
                <p className="mt-1 text-xs text-slate-500">
                  Encrypted at rest. Used by the Instagram worker daemon to log in
                  via Playwright and send DMs.
                </p>
              </div>

              <div>
                <label className="mb-1 block text-sm text-slate-300">
                  DM / day
                </label>
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={200}
                  value={form.dmDailyLimit}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      dmDailyLimit: e.target.value,
                    }))
                  }
                />
              </div>

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
                  !form.username.trim() ||
                  !form.password
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
