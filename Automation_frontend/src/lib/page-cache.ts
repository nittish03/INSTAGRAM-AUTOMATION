"use client";

/**
 * Module-level in-memory cache for already-loaded page datasets.
 *
 * Survives client-side route navigations within the same SPA session.
 * Used so that switching tabs and coming back instantly shows cached
 * data rather than re-flashing skeletons. A silent background refresh
 * still runs to keep numbers current.
 */
type Entry = { data: unknown; expiresAt: number };

const DEFAULT_TTL_MS = 5 * 60_000; // 5 minutes
const cache = new Map<string, Entry>();

export const pageCache = {
  get<T>(key: string): T | null {
    const entry = cache.get(key);
    if (!entry) return null;
    if (entry.expiresAt < Date.now()) {
      cache.delete(key);
      return null;
    }
    return entry.data as T;
  },
  set<T>(key: string, data: T, ttlMs: number = DEFAULT_TTL_MS): void {
    cache.set(key, { data, expiresAt: Date.now() + ttlMs });
  },
  clear(key?: string): void {
    if (key) cache.delete(key);
    else cache.clear();
  },
};
