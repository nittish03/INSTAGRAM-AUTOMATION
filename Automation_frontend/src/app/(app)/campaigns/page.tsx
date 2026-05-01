"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";
import { TableSkeleton } from "@/components/skeleton";
import type { Campaign, LinkedInProfileItem } from "@/lib/types";

const CAMPAIGNS_KEY = "campaigns.list";
const PROFILES_KEY = "linkedin-profiles.list";

type FormState = {
  name: string;
  isFreemium: boolean;
  actionFraction: string;
  bookingLink: string;
  objective: string;
  productDocs: string;
  userIds: number[];
};

const blankForm: FormState = {
  name: "",
  isFreemium: false,
  actionFraction: "0.2",
  bookingLink: "",
  objective: "",
  productDocs: "",
  userIds: [],
};

type ModalMode =
  | { type: "closed" }
  | { type: "create" }
  | { type: "edit"; id: number };

function campaignToForm(c: Campaign): FormState {
  return {
    name: c.name,
    isFreemium: c.isFreemium,
    actionFraction: String(c.actionFraction),
    bookingLink: c.bookingLink || "",
    objective: c.objective || "",
    productDocs: c.productDocs || "",
    userIds: c.users.map((u) => u.id),
  };
}

export default function CampaignsPage() {
  const cachedCampaigns = pageCache.get<Campaign[]>(CAMPAIGNS_KEY);
  const cachedProfiles = pageCache.get<LinkedInProfileItem[]>(PROFILES_KEY);
  const [items, setItems] = useState<Campaign[]>(cachedCampaigns ?? []);
  const [profiles, setProfiles] = useState<LinkedInProfileItem[]>(cachedProfiles ?? []);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(!cachedCampaigns);
  const [submitting, setSubmitting] = useState(false);
  const [mode, setMode] = useState<ModalMode>({ type: "closed" });
  const [form, setForm] = useState<FormState>(blankForm);

  async function loadAll(showSkeleton = false) {
    if (showSkeleton) setLoading(true);
    try {
      const [campaignsRes, profilesRes] = await Promise.all([
        api.campaigns(),
        api.linkedinProfiles(),
      ]);
      setItems(campaignsRes.items);
      setProfiles(profilesRes.items);
      pageCache.set(CAMPAIGNS_KEY, campaignsRes.items);
      pageCache.set(PROFILES_KEY, profilesRes.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load campaigns");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadAll();
  }, []);

  function openCreate() {
    setForm(blankForm);
    setError("");
    setInfo("");
    setMode({ type: "create" });
  }

  function openEdit(c: Campaign) {
    setForm(campaignToForm(c));
    setError("");
    setInfo("");
    setMode({ type: "edit", id: c.id });
  }

  function closeModal() {
    if (submitting) return;
    setMode({ type: "closed" });
  }

  function toggleUser(userId: number) {
    setForm((f) =>
      f.userIds.includes(userId)
        ? { ...f, userIds: f.userIds.filter((id) => id !== userId) }
        : { ...f, userIds: [...f.userIds, userId] },
    );
  }

  async function submitCampaign() {
    if (!form.name.trim()) {
      setError("Campaign name is required.");
      return;
    }
    if (form.userIds.length === 0) {
      setError("Select at least one account to link this campaign to.");
      return;
    }
    setSubmitting(true);
    setError("");
    setInfo("");
    try {
      const payload = {
        name: form.name.trim(),
        isFreemium: form.isFreemium,
        actionFraction: Number(form.actionFraction || 0.2),
        bookingLink: form.bookingLink.trim(),
        objective: form.objective.trim(),
        productDocs: form.productDocs.trim(),
        userIds: form.userIds,
      };

      if (mode.type === "edit") {
        await api.updateCampaign(mode.id, payload);
        setInfo("Campaign updated successfully.");
      } else {
        await api.createCampaign(payload);
        setInfo("Campaign created successfully.");
      }

      setMode({ type: "closed" });
      setForm(blankForm);
      pageCache.clear(CAMPAIGNS_KEY);
      await loadAll();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : mode.type === "edit"
            ? "Failed to update campaign"
            : "Failed to create campaign",
      );
    } finally {
      setSubmitting(false);
    }
  }

  const isEdit = mode.type === "edit";
  const isOpen = mode.type !== "closed";

  return (
    <div className="space-y-4">
      <section className="card flex items-center justify-between p-5">
        <div>
          <h2 className="text-2xl font-semibold">Campaigns</h2>
          <p className="mt-1 text-sm text-slate-400">
            Each campaign runs against the LinkedIn accounts it is linked to. The
            ICP / product description on a campaign decides who the bot reaches out to.
          </p>
        </div>
        <button
          aria-label="Add campaign"
          className="btn-primary flex h-10 w-10 items-center justify-center px-0! text-2xl"
          onClick={openCreate}
        >
          +
        </button>
      </section>

      {error && !isOpen ? <p className="text-sm text-rose-400">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-400">{info}</p> : null}

      {loading ? (
        <TableSkeleton rows={6} cols={6} />
      ) : items.length === 0 ? (
        <section className="card p-8 text-center text-sm text-slate-400">
          No campaigns yet. Click the <strong>+</strong> button above to create one and link
          it to a LinkedIn account.
        </section>
      ) : (
        <section className="card overflow-hidden">
          <div className="h-[calc(100vh-15rem)] min-h-88 overflow-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">Name</th>
                  <th className="th">Type</th>
                  <th className="th">Action Fraction</th>
                  <th className="th">ICP / Product</th>
                  <th className="th">Booking Link</th>
                  <th className="th">Linked accounts</th>
                  <th className="th w-24">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((c) => {
                  const icpPreview = (c.productDocs || "").trim();
                  return (
                    <tr key={c.id}>
                      <td className="td">{c.name}</td>
                      <td className="td">{c.isFreemium ? "Freemium" : "Regular"}</td>
                      <td className="td">{c.actionFraction}</td>
                      <td className="td max-w-xs">
                        {icpPreview ? (
                          <span
                            className="block truncate text-slate-300"
                            title={icpPreview}
                          >
                            {icpPreview}
                          </span>
                        ) : (
                          <span className="text-amber-300">not set</span>
                        )}
                      </td>
                      <td className="td">
                        {c.bookingLink ? (
                          <a
                            href={c.bookingLink}
                            target="_blank"
                            className="text-violet-300 hover:underline"
                            rel="noreferrer"
                          >
                            Open
                          </a>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className="td">
                        {c.users.length === 0 ? (
                          <span className="text-rose-300">no account linked</span>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {c.users.map((u) => (
                              <span
                                key={u.id}
                                className="rounded-full bg-violet-500/15 px-2 py-0.5 text-xs text-violet-200"
                              >
                                {u.username}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="td">
                        <button className="btn-secondary" onClick={() => openEdit(c)}>
                          Edit
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {isOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4"
          onClick={closeModal}
        >
          <div
            className="card max-h-[90vh] w-full max-w-2xl space-y-4 overflow-y-auto p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold">
                {isEdit ? "Edit campaign" : "Add new campaign"}
              </h3>
              <button
                className="text-slate-400 hover:text-slate-200"
                onClick={closeModal}
                disabled={submitting}
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            {error ? <p className="text-sm text-rose-400">{error}</p> : null}

            <div className="grid gap-3 md:grid-cols-2">
              <div className="md:col-span-2">
                <label className="mb-1 block text-sm text-slate-300">Name</label>
                <input
                  className="input"
                  placeholder="e.g. Q3 outbound"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  autoFocus
                />
              </div>

              <div>
                <label className="mb-1 block text-sm text-slate-300">
                  Action fraction (0-1)
                </label>
                <input
                  className="input"
                  type="number"
                  min={0.01}
                  max={1}
                  step={0.01}
                  value={form.actionFraction}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, actionFraction: e.target.value }))
                  }
                />
              </div>

              <div className="flex items-end">
                <label className="inline-flex items-center gap-2 text-sm text-slate-300">
                  <input
                    type="checkbox"
                    checked={form.isFreemium}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, isFreemium: e.target.checked }))
                    }
                  />
                  Freemium campaign
                </label>
              </div>

              <div className="md:col-span-2">
                <label className="mb-1 block text-sm text-slate-300">
                  Booking link (optional)
                </label>
                <input
                  className="input"
                  placeholder="https://cal.com/..."
                  value={form.bookingLink}
                  onChange={(e) => setForm((f) => ({ ...f, bookingLink: e.target.value }))}
                />
              </div>

              <div className="md:col-span-2">
                <label className="mb-1 block text-sm text-slate-300">
                  Objective (optional)
                </label>
                <input
                  className="input"
                  placeholder="e.g. Book sales calls"
                  value={form.objective}
                  onChange={(e) => setForm((f) => ({ ...f, objective: e.target.value }))}
                />
              </div>

              <div className="md:col-span-2">
                <label className="mb-1 block text-sm text-slate-300">
                  ICP / product description
                </label>
                <textarea
                  className="input min-h-[160px] w-full"
                  placeholder="Describe who you sell to, what you offer, and the kind of leads this campaign should target. The bot uses this to qualify and message prospects."
                  value={form.productDocs}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, productDocs: e.target.value }))
                  }
                />
                <p className="mt-1 text-xs text-slate-500">
                  This replaces the one-time onboarding ICP. Update it any time and
                  this campaign&apos;s outreach adapts to it.
                </p>
              </div>
            </div>

            <div>
              <label className="mb-2 block text-sm text-slate-300">
                Link to LinkedIn account(s)
              </label>
              {profiles.length === 0 ? (
                <p className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
                  No LinkedIn profiles found. Add a profile first.
                </p>
              ) : (
                <div className="grid gap-2 sm:grid-cols-2">
                  {profiles.map((p) => {
                    const checked = form.userIds.includes(p.userId);
                    return (
                      <label
                        key={p.id}
                        className={`flex cursor-pointer items-start gap-2 rounded-lg border p-3 text-sm ${
                          checked
                            ? "border-violet-400/60 bg-violet-500/10"
                            : "border-slate-700 hover:border-slate-500"
                        }`}
                      >
                        <input
                          type="checkbox"
                          className="mt-0.5"
                          checked={checked}
                          onChange={() => toggleUser(p.userId)}
                        />
                        <div>
                          <div className="font-medium text-slate-100">{p.djangoUser}</div>
                          <div className="text-xs text-slate-400">
                            {p.linkedinUsername || p.djangoEmail}
                          </div>
                        </div>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                className="btn-secondary"
                onClick={closeModal}
                disabled={submitting}
              >
                Cancel
              </button>
              <button
                className="btn-primary"
                onClick={submitCampaign}
                disabled={submitting || !form.name.trim() || form.userIds.length === 0}
              >
                {submitting
                  ? isEdit
                    ? "Saving..."
                    : "Creating..."
                  : isEdit
                    ? "Save changes"
                    : "Create campaign"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
