import type { SafeModeSettings } from "@/lib/types";

export function SafeModeBanner({ settings }: { settings: SafeModeSettings | null }) {
  if (!settings) return null;
  return (
    <section className={`card p-4 ${settings.globalPauseOutreach || settings.pauseNewConnectionInvites ? "border-rose-700" : ""}`}>
      <p className="text-sm font-semibold">
        Safe Mode: {settings.enabled ? "Enabled" : "Disabled"}
      </p>
      <p className="mt-1 text-xs text-slate-400">
        Global pause: {settings.globalPauseOutreach ? "On" : "Off"} | New invites paused: {settings.pauseNewConnectionInvites ? "On" : "Off"} | Max bulk approve: {settings.maxBulkApprove} | Max bulk export: {settings.maxBulkExport}
      </p>
    </section>
  );
}

