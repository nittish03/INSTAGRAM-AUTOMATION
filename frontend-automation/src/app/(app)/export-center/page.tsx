"use client";

import { useEffect, useMemo, useState } from "react";

import { confirmWithSafety } from "@/components/confirmation-dialog";
import { ExportPreviewTable } from "@/components/export-preview-table";
import { PageHeader } from "@/components/page-header";
import { api } from "@/lib/api";
import type { ExportPreviewItem } from "@/lib/types";

export default function ExportCenterPage() {
  const [exportable, setExportable] = useState<ExportPreviewItem[]>([]);
  const [skipped, setSkipped] = useState<ExportPreviewItem[]>([]);
  const [selected, setSelected] = useState<Record<number, boolean>>({});
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  async function load() {
    try {
      const data = await api.exportPreview();
      setExportable(data.exportable);
      setSkipped(data.skipped);
      setSelected({});
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load export preview");
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, []);

  const selectedIds = useMemo(
    () => Object.entries(selected).filter(([, v]) => v).map(([k]) => Number(k)),
    [selected],
  );

  async function exportNow() {
    if (!selectedIds.length) return;
    if (!confirmWithSafety(`Export ${selectedIds.length} leads to Google Sheet?`)) return;
    try {
      const data = await api.exportSelected(selectedIds);
      setInfo(`Exported ${data.exported}, failed ${data.failed}.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Export Center"
        description="Preview and control Google Sheet exports with explicit skip reasons."
        actions={<button className="btn-primary" onClick={() => void exportNow()} disabled={!selectedIds.length}>Export Selected ({selectedIds.length})</button>}
      />
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-300">{info}</p> : null}
      <ExportPreviewTable
        exportable={exportable}
        skipped={skipped}
        selected={selected}
        onToggle={(leadId) => setSelected((cur) => ({ ...cur, [leadId]: !cur[leadId] }))}
      />
    </div>
  );
}

