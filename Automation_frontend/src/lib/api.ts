"use client";

import type {
  ActionLog,
  AnalyticsData,
  Campaign,
  DashboardStats,
  Deal,
  DraftMessage,
  GoogleSheetItem,
  GoogleStatus,
  Lead,
  LinkedInProfileItem,
  MessagingDiagnostics,
  SearchKeywordItem,
  SiteConfig,
  SiteConfigResponse,
  TaskItem,
  User,
} from "@/lib/types";

type ApiResult<T> = { ok: boolean; error?: string } & T;
type CacheEntry = {
  data: unknown;
  expiresAt: number;
};

const CACHE_TTL_MS = 60_000; // 60s default page-data cache
const responseCache = new Map<string, CacheEntry>();
const inflight = new Map<string, Promise<unknown>>();

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(new RegExp(`(?:^|; )${encodeURIComponent(name)}=([^;]*)`));
  return m ? decodeURIComponent(m[1]!) : null;
}

function cacheKeyFor(path: string) {
  return path;
}

function clearApiCache() {
  responseCache.clear();
  inflight.clear();
}

async function request<T>(
  path: string,
  init?: RequestInit,
  options?: { cacheTtlMs?: number; bypassCache?: boolean },
): Promise<ApiResult<T>> {
  const method = (init?.method || "GET").toUpperCase();
  const isRead = method === "GET";
  const cacheKey = cacheKeyFor(path);
  const ttl = options?.cacheTtlMs ?? CACHE_TTL_MS;
  const now = Date.now();

  if (isRead && !options?.bypassCache) {
    const cached = responseCache.get(cacheKey);
    if (cached && cached.expiresAt > now) {
      return cached.data as ApiResult<T>;
    }
    const pending = inflight.get(cacheKey);
    if (pending) {
      return (await pending) as ApiResult<T>;
    }
  }

  const csrftoken = readCookie("csrftoken");
  const run = (async () => {
    const res = await fetch(`/api/backend${path}`, {
      ...init,
      credentials: "include",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...(csrftoken ? { "X-CSRFToken": csrftoken } : {}),
        ...(init?.headers || {}),
      },
    });
    const contentType = res.headers.get("content-type") || "";
    const raw = await res.text();
    const data =
      contentType.includes("application/json") && raw
        ? JSON.parse(raw)
        : ({ ok: false, error: raw || `Unexpected response (${res.status})` } as Record<string, unknown>);
    if (!res.ok) {
      if (res.redirected || (res.status >= 300 && res.status < 400)) {
        throw new Error(
          `Got redirect (${res.status}) fetching API — disable cache / hard reload (DevTools Network: disable cache)`,
        );
      }
      throw new Error(data?.error || `Request failed (${res.status})`);
    }
    return data as ApiResult<T>;
  })();

  if (isRead && !options?.bypassCache) {
    inflight.set(cacheKey, run as Promise<unknown>);
  }

  try {
    const data = await run;
    if (isRead && !options?.bypassCache) {
      responseCache.set(cacheKey, { data, expiresAt: now + ttl });
    } else if (!isRead) {
      // Writes can affect list/detail pages; clear to avoid stale UX.
      clearApiCache();
    }
    return data;
  } finally {
    if (isRead && !options?.bypassCache) inflight.delete(cacheKey);
  }
}

export const api = {
  /** Seeds csrftoken cookie; safe to skip before login — login endpoint is csrf-exempt. */
  csrf: () => request<{ csrfToken: string }>("/api/csrf"),
  login: (username: string, password: string) =>
    request<{ user: User }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<Record<string, never>>("/api/auth/logout", { method: "POST" }),
  me: () => request<{ user: User }>("/api/auth/me"),
  dashboard: () => request<{ stats: DashboardStats; google: { connected: boolean; email: string } }>("/api/dashboard"),
  campaigns: () => request<{ items: Campaign[] }>("/api/campaigns"),
  createCampaign: (payload: {
    name: string;
    isFreemium?: boolean;
    actionFraction?: number;
    bookingLink?: string;
    objective?: string;
    userIds?: number[];
  }) =>
    request<{ item: Campaign }>("/api/campaigns", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  leads: (params: URLSearchParams) => request<{ items: Lead[]; pagination: { page: number; pageSize: number; total: number } }>(`/api/leads?${params.toString()}`),
  deals: (params: URLSearchParams) => request<{ items: Deal[]; pagination: { page: number; pageSize: number; total: number } }>(`/api/deals?${params.toString()}`),
  tasks: (params: URLSearchParams) => request<{ items: TaskItem[]; pagination: { page: number; pageSize: number; total: number } }>(`/api/tasks?${params.toString()}`),
  drafts: () => request<{ items: DraftMessage[] }>("/api/messages/drafts"),
  approveDrafts: (ids: number[]) =>
    request<{ approved: number }>("/api/messages/drafts/approve", {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),
  messagingDiagnostics: () =>
    request<{ diagnostics: MessagingDiagnostics }>("/api/messaging/diagnostics", undefined, { bypassCache: true }),
  messagingHeal: () =>
    request<{ enqueued: number; skipped: number }>("/api/messaging/heal", {
      method: "POST",
      body: JSON.stringify({}),
    }),
  actionLogs: (params: URLSearchParams) =>
    request<{ items: ActionLog[]; pagination: { page: number; pageSize: number; total: number } }>(
      `/api/action-logs?${params.toString()}`,
    ),
  linkedinProfiles: () => request<{ items: LinkedInProfileItem[] }>("/api/linkedin-profiles"),
  toggleLinkedinProfile: (profileId: number) =>
    request<{ active: boolean }>(`/api/linkedin-profiles/${profileId}/toggle`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  searchKeywords: (params: URLSearchParams) =>
    request<{ items: SearchKeywordItem[]; pagination: { page: number; pageSize: number; total: number } }>(
      `/api/search-keywords?${params.toString()}`,
    ),
  createSearchKeyword: (campaignId: number, keyword: string) =>
    request<{ created: boolean; item: SearchKeywordItem }>("/api/search-keywords/create", {
      method: "POST",
      body: JSON.stringify({ campaignId, keyword }),
    }),
  deleteSearchKeyword: (id: number) =>
    request<Record<string, never>>(`/api/search-keywords/${id}`, { method: "DELETE" }),
  siteConfig: () => request<SiteConfigResponse>("/api/site-config"),
  saveSiteConfig: (patch: Partial<SiteConfig> & { llmApiKey?: string }) =>
    request<Record<string, never>>("/api/site-config/save", {
      method: "POST",
      body: JSON.stringify(patch),
    }),
  analytics: (days = 14) =>
    request<AnalyticsData>(`/api/analytics?days=${days}`),
  googleStatus: () => request<{ google: GoogleStatus }>("/api/google/status"),
  googleSheets: () => request<{ items: GoogleSheetItem[] }>("/api/google/sheets"),
  invalidateCache: () => clearApiCache(),
};
