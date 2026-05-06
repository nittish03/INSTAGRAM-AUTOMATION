"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { GoogleGridCellStyle } from "@/lib/types";

const MIN_ROWS = 10;
const MIN_COLS = 26;

function colLabel(index: number): string {
  let s = "";
  let n = index;
  while (n >= 0) {
    s = String.fromCharCode(65 + (n % 26)) + s;
    n = Math.floor(n / 26) - 1;
  }
  return s;
}

function rgbFromGoogle(colorObj?: Record<string, number>): string {
  if (!colorObj) return "";
  const has = (k: string) => typeof colorObj[k] === "number" && Number.isFinite(colorObj[k]);
  if (!has("red") && !has("green") && !has("blue")) return "";
  const r = Math.round((has("red") ? colorObj.red : 0) * 255);
  const g = Math.round((has("green") ? colorObj.green : 0) * 255);
  const b = Math.round((has("blue") ? colorObj.blue : 0) * 255);
  return `rgb(${r}, ${g}, ${b})`;
}

function padGrid(values: string[][], stylesIn: GoogleGridCellStyle[][]) {
  const data = (values || []).map((r) => (Array.isArray(r) ? [...r] : []));
  const styles = (stylesIn || []).map((r) => (Array.isArray(r) ? [...r] : []));
  const cols = Math.max(MIN_COLS, data.reduce((m, r) => Math.max(m, r.length), 0));

  data.forEach((r) => {
    while (r.length < cols) r.push("");
  });
  while (data.length < MIN_ROWS) {
    data.push(Array.from({ length: cols }, () => ""));
  }

  while (styles.length < data.length) styles.push([]);
  styles.forEach((r, i) => {
    while (r.length < data[i]!.length) r.push({});
  });

  return { data, styles };
}

export function GoogleSheetEditor({ spreadsheetId }: { spreadsheetId: string }) {
  const [title, setTitle] = useState("");
  const [spreadsheetUrl, setSpreadsheetUrl] = useState("");
  const [sheetTabs, setSheetTabs] = useState<string[]>([]);
  const [rangeInput, setRangeInput] = useState("Sheet1!A1:ZZ500");
  const [rangeA1, setRangeA1] = useState("Sheet1!A1:ZZ500");
  const [grid, setGrid] = useState<string[][]>([]);
  const [styles, setStyles] = useState<GoogleGridCellStyle[][]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [autosave, setAutosave] = useState(true);

  const dirtyRef = useRef(false);
  const autosaveRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const meta = await api.googleSheetMeta(spreadsheetId);
        if (!mounted) return;
        setTitle(meta.title || "(untitled)");
        setSpreadsheetUrl(meta.spreadsheetUrl || "");
        setSheetTabs(meta.sheetTabs || []);
      } catch (e) {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : "Failed to load spreadsheet");
      }
    })();
    return () => {
      mounted = false;
    };
  }, [spreadsheetId]);

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const resp = await api.googleSheetGrid(spreadsheetId, rangeA1);
        if (!mounted) return;
        const padded = padGrid(resp.values || [], resp.styles || []);
        setGrid(padded.data);
        setStyles(padded.styles);
        dirtyRef.current = false;
      } catch (e) {
        if (!mounted) return;
        setError(e instanceof Error ? e.message : "Failed to load sheet grid");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [spreadsheetId, rangeA1]);

  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (dirtyRef.current) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);

  async function saveNow() {
    setStatus("Saving...");
    try {
      const res = await api.googleSheetSave(spreadsheetId, rangeA1, grid);
      dirtyRef.current = false;
      setStatus(`Saved ${new Date().toLocaleTimeString()} -> ${res.updatedRange || rangeA1}`);
    } catch (e) {
      setStatus(`Save failed: ${e instanceof Error ? e.message : "unknown error"}`);
    }
  }

  function scheduleAutosave() {
    if (!autosave) return;
    dirtyRef.current = true;
    if (autosaveRef.current) clearTimeout(autosaveRef.current);
    autosaveRef.current = setTimeout(() => {
      autosaveRef.current = null;
      void saveNow();
    }, 1200);
  }

  function updateCell(r: number, c: number, value: string) {
    setGrid((prev) => {
      const next = prev.map((row) => [...row]);
      next[r]![c] = value;
      return next;
    });
    dirtyRef.current = true;
    scheduleAutosave();
  }

  function addRow() {
    setGrid((prev) => {
      const cols = Math.max(MIN_COLS, prev.reduce((m, r) => Math.max(m, r.length), 0));
      return [...prev, Array.from({ length: cols }, () => "")];
    });
    setStyles((prev) => {
      const cols = Math.max(MIN_COLS, grid.reduce((m, r) => Math.max(m, r.length), 0));
      return [...prev, Array.from({ length: cols }, () => ({}))];
    });
    dirtyRef.current = true;
    scheduleAutosave();
  }

  function addColumn() {
    setGrid((prev) => prev.map((r) => [...r, ""]));
    setStyles((prev) => prev.map((r) => [...r, {}]));
    dirtyRef.current = true;
    scheduleAutosave();
  }

  const cols = Math.max(MIN_COLS, grid.reduce((m, r) => Math.max(m, r.length), 0));

  return (
    <div className="space-y-4">
      <div>
        <Link href="/google" className="text-sm text-violet-300 hover:underline">
          {"<- All sheets"}
        </Link>
        <h2 className="mt-1 text-xl font-semibold text-slate-100">{title || "Spreadsheet"}</h2>
        {spreadsheetUrl ? (
          <a href={spreadsheetUrl} target="_blank" rel="noreferrer" className="text-sm text-slate-400 hover:underline">
            Open in Google Sheets
          </a>
        ) : null}
      </div>

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setRangeA1(rangeInput.trim() || "Sheet1!A1:ZZ500");
        }}
      >
        <label className="text-sm text-slate-400">Range:</label>
        <input className="input min-w-[260px] flex-1 font-mono text-xs" value={rangeInput} onChange={(e) => setRangeInput(e.target.value)} />
        <button className="btn-secondary" type="submit">
          Load
        </button>
      </form>

      {sheetTabs.length > 0 ? (
        <div className="text-xs text-slate-500">
          Tabs: {sheetTabs.map((t) => <span key={t} className="mr-1 rounded bg-slate-800 px-2 py-0.5">{t}</span>)}
        </div>
      ) : null}

      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      <section className="card p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <button className="btn-secondary text-sm" type="button" onClick={addRow}>+ Row</button>
          <button className="btn-secondary text-sm" type="button" onClick={addColumn}>+ Column</button>
          <label className="ml-2 flex items-center gap-2 text-sm text-slate-400">
            <input type="checkbox" checked={autosave} onChange={(e) => setAutosave(e.target.checked)} />
            Auto-save
          </label>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-slate-500">{status}</span>
            <button className="btn-primary text-sm" type="button" onClick={() => void saveNow()}>
              Save changes
            </button>
          </div>
        </div>

        {loading ? (
          <p className="text-sm text-slate-400">Loading grid...</p>
        ) : (
          <div className="h-[calc(100vh-20rem)] min-h-72 overflow-auto rounded-lg border border-slate-800">
            <div className="min-w-max">
              <div className="grid border-b border-slate-700 bg-slate-900" style={{ gridTemplateColumns: `44px repeat(${cols}, minmax(90px, 1fr))` }}>
                <div className="border-r border-slate-700" />
                {Array.from({ length: cols }).map((_, c) => (
                  <div key={`h-${c}`} className="border-r border-slate-700 py-2 text-center text-xs font-semibold text-slate-400">
                    {colLabel(c)}
                  </div>
                ))}
              </div>
              {grid.map((row, r) => (
                <div key={`r-${r}`} className="grid border-b border-slate-800" style={{ gridTemplateColumns: `44px repeat(${cols}, minmax(90px, 1fr))` }}>
                  <div className="flex items-center justify-center border-r border-slate-700 bg-slate-900 text-xs text-slate-500">{r + 1}</div>
                  {Array.from({ length: cols }).map((_, c) => {
                    const st = styles[r]?.[c] || {};
                    const bg = rgbFromGoogle(st.bg);
                    const text = rgbFromGoogle(st.text);
                    const align = st.align === "RIGHT" ? "right" : st.align === "CENTER" ? "center" : "left";
                    return (
                      <input
                        key={`c-${r}-${c}`}
                        value={row[c] ?? ""}
                        onChange={(e) => updateCell(r, c, e.target.value)}
                        className="border-r border-slate-800 px-2 py-1 text-sm outline-none focus:ring-1 focus:ring-inset focus:ring-violet-500"
                        style={{
                          background: bg || undefined,
                          color: text || undefined,
                          textAlign: align as "left" | "center" | "right",
                          fontWeight: st.bold ? 700 : 400,
                          fontStyle: st.italic ? "italic" : "normal",
                        }}
                        onDoubleClick={() => {
                          if (st.hyperlink) window.open(st.hyperlink, "_blank", "noopener,noreferrer");
                        }}
                      />
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

