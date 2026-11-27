"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ago, api, type Form, STATUS_LABEL, type Summary } from "@/lib/console/api";
import s from "./console.module.css";
import TopBar from "./TopBar";

const TABS = ["needs_review", "blocked", "failed", "approved", "submitted", "rejected", "all"] as const;
type Tab = (typeof TABS)[number];
type Upload = { records: number; outcomes: Record<string, number>; warnings: string[] };

export default function Queue() {
  const [tab, setTab] = useState<Tab>("needs_review");
  const [rows, setRows] = useState<Summary[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [forms, setForms] = useState<Form[]>([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (tab !== "all") params.set("status", tab);
      if (q.trim()) params.set("q", q.trim());
      const [list, c] = await Promise.all([api<Summary[]>(`enrollments?${params}`), api<Record<string, number>>("enrollments/counts")]);
      setRows(list);
      setCounts(c);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [tab, q]);

  useEffect(() => { void load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);
  useEffect(() => { api<Form[]>("forms").then(setForms).catch(() => setForms([])); }, []);

  const portal = (id: string) => forms.find((f) => f.id === id)?.portal ?? id;
  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <>
      <TopBar active="queue" />
      <main className={s.page}>
        <div className={s.pageHead}>
          <div>
            <h1 className={s.title}>Queue</h1>
            <p className={s.subtle}>Records that need a decision come first. Opening one shows personal data and is logged.</p>
          </div>
        </div>

        <Intake forms={forms} onDone={load} />

        {error && <p className={s.errorBox} role="alert">{error}</p>}

        <div className={s.tabs} role="tablist" aria-label="Filter by status">
          {TABS.map((t) => (
            <button key={t} type="button" role="tab" className={s.tab} aria-selected={tab === t} onClick={() => setTab(t)} data-testid={`tab-${t}`}>
              {t === "all" ? "All" : STATUS_LABEL[t]}
              <span className={s.count}>{t === "all" ? total : counts[t] ?? 0}</span>
            </button>
          ))}
        </div>
        <div className={s.toolbar}>
          <input className={s.input} type="search" placeholder="Find by enrollment ID or portal reference" aria-label="Find by enrollment ID or portal reference"
            value={q} onChange={(e) => setQ(e.target.value)} style={{ minWidth: 320 }} />
          <button type="button" className={s.btn} onClick={load}>Refresh</button>
        </div>

        {rows && rows.length === 0 && (
          <div className={s.empty}>{tab === "needs_review" ? "Nothing is waiting for review." : "No records here."}</div>
        )}
        {rows && rows.length > 0 && (
          <table className={s.table} data-testid="queue-table">
            <thead>
              <tr>
                <th>Enrollment</th><th>Portal</th><th className={s.hideSm}>Source</th><th>Outcome</th>
                <th>Needs attention</th><th className={`${s.num} ${s.hideSm}`}>Lowest confidence</th><th className={s.hideSm}>Updated</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const top = r.reasons.find((x) => x.severity === "block") ?? r.reasons.find((x) => x.severity === "review")
                  ?? r.reasons.find((x) => x.code === "SIGNOFF_REQUIRED");
                const extra = r.reasons.filter((x) => x.severity !== "info").length - 1;
                return (
                  <tr key={r.enrollment_id}>
                    <td>
                      <Link href={`/console/enrollments/${r.enrollment_id}`} className={`${s.rowLink} ${s.mono}`}>{r.enrollment_id}</Link>
                      {r.status !== tab && <div className={s.subtle}>{STATUS_LABEL[r.status] ?? r.status}</div>}
                    </td>
                    <td>{portal(r.target_form)}</td>
                    <td className={s.hideSm}>{r.source}</td>
                    <td>{r.outcome ? <span className={`${s.pill} ${s[r.outcome]}`}>{r.outcome.replace("_", " ")}</span> : "–"}</td>
                    <td className={s.reasonCell}>
                      {r.confirmation_ref ? <span className={s.mono}>{r.confirmation_ref}</span> : top ? top.message : "—"}
                      {extra > 0 && !r.confirmation_ref && <span> (+{extra} more)</span>}
                    </td>
                    <td className={`${s.num} ${s.hideSm}`}>{r.min_confidence == null ? "–" : `${Math.round(r.min_confidence * 100)}%`}</td>
                    <td className={s.hideSm}>{ago(r.updated_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </main>
    </>
  );
}

function Intake({ forms, onDone }: { forms: Form[]; onDone: () => void }) {
  const [form, setForm] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState<"" | "file" | "notes">("");
  const [result, setResult] = useState("");
  const target = form || forms[0]?.id || "";

  const summary = (u: Upload) => {
    const parts = Object.entries(u.outcomes).map(([k, n]) => `${n} ${k.replace("_", " ").toLowerCase()}`);
    return `${u.records} record${u.records === 1 ? "" : "s"}: ${parts.join(", ")}.${u.warnings.length ? ` ${u.warnings.join(" ")}` : ""}`;
  };

  const upload = async () => {
    if (!file) return;
    setBusy("file");
    try {
      const data = new FormData();
      data.set("target_form", target);
      data.set("file", file);
      setResult(summary(await api<Upload>("intake/upload", { method: "POST", form: data })));
      onDone();
    } catch (e) {
      setResult((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const addNotes = async () => {
    setBusy("notes");
    try {
      const r = await api<Summary & { duplicate: boolean }>("intake/notes", { method: "POST", json: { target_form: target, text: notes } });
      setResult(`${r.enrollment_id}: ${r.outcome?.replace("_", " ").toLowerCase()}${r.duplicate ? " (already received)" : ""}.`);
      setNotes("");
      onDone();
    } catch (e) {
      setResult((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  return (
    <section className={s.intake} aria-label="Add records">
      <div className={s.panel}>
        <h2 className={s.panelTitle}>Upload a file</h2>
        <div className={s.panelRow}>
          <select className={s.select} aria-label="Portal" value={target} onChange={(e) => setForm(e.target.value)}>
            {forms.map((f) => <option key={f.id} value={f.id}>{f.portal}</option>)}
          </select>
          <input type="file" aria-label="File" accept=".csv,.json,.pdf,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} data-testid="upload-file" />
          <button type="button" className={s.btn} onClick={upload} disabled={!file || busy !== ""}>{busy === "file" ? "Reading…" : "Upload"}</button>
        </div>
        <p className={s.result}>CSV, JSON, PDF or a text file. The same file twice adds nothing new.</p>
      </div>
      <div className={s.panel}>
        <h2 className={s.panelTitle}>Paste call notes or an email</h2>
        <textarea className={`${s.input} ${s.notes}`} aria-label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <div className={s.panelRow}>
          <button type="button" className={s.btn} onClick={addNotes} disabled={!notes.trim() || busy !== ""}>{busy === "notes" ? "Reading…" : "Add notes"}</button>
        </div>
      </div>
      {result && <p className={s.result} role="status" data-testid="intake-result" style={{ gridColumn: "1 / -1", margin: 0 }}>{result}</p>}
    </section>
  );
}
