"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { Skeleton } from "@/components/skeleton";
import type { User } from "@/lib/types";

const navSections = [
  {
    title: "Dashboard",
    items: [
      { href: "/home", label: "Home", icon: "🏠" },
      { href: "/dashboard", label: "Control Center", icon: "🎛️" },
      { href: "/workbench", label: "Workbench", icon: "🧭" },
      { href: "/analytics", label: "Analytics", icon: "📊" },
      { href: "/campaign-health", label: "Campaign Health", icon: "❤️" },
    ],
  },
  {
    title: "LinkedIn",
    items: [
      { href: "/action-logs", label: "Action logs", icon: "🧾" },
      { href: "/campaigns", label: "Campaigns", icon: "📣" },
      { href: "/linkedin-profiles", label: "LinkedIn profiles", icon: "👤" },
      { href: "/search-keywords", label: "Search keywords", icon: "🔎" },
      { href: "/site-configuration", label: "Site configuration", icon: "⚙️" },
      { href: "/tasks", label: "Tasks", icon: "✅" },
    ],
  },
  {
    title: "CRM",
    items: [
      { href: "/leads", label: "Leads", icon: "🧑‍💼" },
      { href: "/deals", label: "Deals", icon: "🤝" },
      { href: "/follow-up-suggestions", label: "Follow-up Suggestions", icon: "🧠" },
      { href: "/export-center", label: "Export Center", icon: "📤" },
      { href: "/recovery", label: "Recovery", icon: "🛠️" },
      { href: "/safety", label: "Safety", icon: "🛡️" },
    ],
  },
  {
    title: "Chat",
    items: [{ href: "/messages", label: "Messages", icon: "💬" }],
  },
  {
    title: "Google",
    items: [{ href: "/google", label: "Google Workspace", icon: "📄" }],
  },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const me = await api.me();
        if (mounted) setUser(me.user);
      } catch {
        if (mounted) router.replace("/login");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [router]);

  async function onLogout() {
    try {
      await api.logout();
      router.replace("/login");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Logout failed");
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen p-4">
        <div className="mx-auto flex max-w-[1600px] items-start gap-4">
          <aside className="card flex h-[calc(100vh-2rem)] w-64 shrink-0 flex-col overflow-hidden p-4">
            <Skeleton className="mb-6 h-6 w-40 shrink-0" />
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
              {Array.from({ length: 12 }).map((_, i) => (
                <Skeleton key={i} className="h-9 w-full shrink-0" />
              ))}
            </div>
          </aside>
          <main className="min-w-0 flex-1 space-y-4">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-64 w-full" />
          </main>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <div className="mx-auto flex max-w-[1600px] items-start gap-4 p-4">
        <aside className="card sticky top-4 flex h-[calc(100vh-2rem)] w-64 shrink-0 flex-col overflow-hidden p-4">
          <div className="shrink-0 pt-0.5">
            <h1 className="text-xl font-bold text-violet-300">Leadway</h1>
          </div>
          <nav className="mt-5 min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-y-contain pr-1 [-webkit-overflow-scrolling:touch]">
            {navSections.map((section) => (
              <div key={section.title}>
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {section.title}
                </div>
                <div className="space-y-1">
                  {section.items.map((item) => {
                    const active = pathname === item.href;
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        className={`block rounded-lg px-3 py-2 text-sm ${
                          active ? "bg-violet-600/25 text-violet-200" : "text-slate-300 hover:bg-slate-800"
                        }`}
                      >
                        <span className="flex items-center gap-2.5">
                          <span className="inline-flex size-[1.125rem] shrink-0 items-center justify-center text-[0.875rem] leading-none">
                            {item.icon}
                          </span>
                          <span>{item.label}</span>
                        </span>
                      </Link>
                    );
                  })}
                </div>
              </div>
            ))}
          </nav>

          <div className="mt-4 shrink-0 rounded-lg border border-slate-800 bg-slate-950/70 p-3">
            <div className="text-xs text-slate-400">Signed in as</div>
            <div className="truncate text-sm font-medium text-slate-200">
              {user?.firstName || user?.username}
            </div>
            <div className="truncate text-xs text-slate-500">{user?.email}</div>
            <button onClick={onLogout} className="btn-secondary mt-3 w-full">
              Logout
            </button>
            {error ? <p className="mt-2 text-xs text-rose-400">{error}</p> : null}
          </div>
        </aside>

        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}
