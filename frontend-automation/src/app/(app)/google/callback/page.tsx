"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { api } from "@/lib/api";
import { pageCache } from "@/lib/page-cache";

/**
 * Frontend OAuth callback.
 * Google redirects to /google/callback and we exchange code+state via API.
 */
export default function GoogleCallbackPage() {
  const router = useRouter();
  const params = useSearchParams();
  const ranRef = useRef(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("Finishing Google sign-in...");

  useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;
    let mounted = true;

    (async () => {
      const code = (params.get("code") || "").trim();
      const state = (params.get("state") || "").trim();
      const err = (params.get("error") || "").trim();
      if (err) {
        if (mounted) setError(`Google OAuth error: ${err}`);
        return;
      }
      if (!code || !state) {
        if (mounted) setError("Missing OAuth code/state in callback URL.");
        return;
      }
      try {
        await api.googleAuthExchange(code, state);
        pageCache.clear("google.status");
        pageCache.clear("google.sheets");
        if (mounted) setStatus("Connected. Redirecting...");
        router.replace("/google");
      } catch (e) {
        if (mounted) setError(e instanceof Error ? e.message : "Google OAuth exchange failed");
      }
    })();

    return () => {
      mounted = false;
    };
  }, [params, router]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Google sign-in"
        description="Completing OAuth and saving your Google credentials."
      />
      <section className="card p-5">
        {error ? (
          <div className="space-y-3">
            <p className="text-sm text-rose-400">{error}</p>
            <Link href="/google" className="btn-secondary inline-block">
              Back to Google Workspace
            </Link>
          </div>
        ) : (
          <p className="text-sm text-slate-300">{status}</p>
        )}
      </section>
    </div>
  );
}
