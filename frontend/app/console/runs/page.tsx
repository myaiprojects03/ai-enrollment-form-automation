"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, type Form } from "@/lib/console/api";
import s from "../console.module.css";
import TopBar from "../TopBar";

type HistoryRow = {
  run_id: string; enrollment_id: string; target_form: string; enrollment_status: string; attempt: number; path: string;
  status: string; retries_before: number; error_code: string | null; error_detail: string | null;
  confirmation_ref: string | null; started_at: string; duration_ms: number | null; actor: string;
  options: Record<string, string>; screenshots: number;
};
const STATUSES = ["", "succeeded", "failed", "halted", "running"];

export default function RunHistory() {
  const [rows, setRows] = useState<HistoryRow[] | null>(null);
  const [forms, setForms] = useState<Form[]>([]);
  const [status, setStatus] = useState("");
  const [form, setForm] = useState("");
  const [q, setQ] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const params = new URLSearchParams({ limit: "200" });
    if (status) params.set("status", status);
    if (form) params.set("form", form);
    if (q.trim()) params.set("q", q.trim());
    try { setRows(await api<HistoryRow[]>(`runs?${params}`)); setError(""); } catch (e) { setError((e as Error).message); }
  }, [status, form, q]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { api<Form[]>("forms").then(setForms).catch(() => setForms([])); }, []);
  const portal = (id: string) => forms.find((f) => f.id === id)?.portal ?? id;
  const done = (rows ?? []).filter((r) => r.duration_ms != null);
  const mean = done.length ? done.reduce((a, r) => a + (r.duration_ms ?? 0), 0) / done.length / 1000 : 0;

  return (
    <>
      <TopBar active="runs" />
      <main className={s.page}>
        <div className={s.pageHead}>
          <div>
            <h1 className={s.title}>Run history</h1>
            <p className={s.subtle}>Every submission attempt: how long it took, retries before it, errors and the portal&apos;s reference.</p>
          </div>
        </div>
        <div className={s.toolbar}>
          <select className={s.select} aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
            {STATUSES.map((x) => <option key={x} value={x}>{x ? x[0].toUpperCase() + x.slice(1) : "Any status"}</option>)}
          </select>
          <select className={s.select} aria-label="Portal" value={form} onChange={(e) => setForm(e.target.value)}>
            <option value="">Any portal</option>
            {forms.map((f) => <option key={f.id} value={f.id}>{f.portal}</option>)}
          </select>
          <input className={s.input} type="search" placeholder="Enrollment ID or portal reference" aria-label="Enrollment ID or portal reference"
            value={q} onChange={(e) => setQ(e.target.value)} style={{ minWidth: 280 }} />
          {rows && rows.length > 0 && <span className={s.subtle} data-testid="runs-summary">
            {rows.length} attempt{rows.length === 1 ? "" : "s"}, {rows.filter((r) => r.status === "succeeded").length} succeeded, average {mean.toFixed(1)} s</span>}
        </div>
        {error && <p className={s.errorBox} role="alert">{error}</p>}
        {rows && rows.length === 0 && <div className={s.empty}>No submission attempts match.</div>}
        {rows && rows.length > 0 && (
          <table className={s.table} data-testid="runs-table">
            <thead><tr>
              <th>Started</th><th>Enrollment</th><th>Portal</th><th>Attempt</th><th>Path</th><th>Result</th>
              <th className={s.num}>Duration</th><th>Reference or error</th><th className={s.hideSm}>Screenshots</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.run_id}>
                  <td style={{ whiteSpace: "nowrap" }}>{new Date(r.started_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</td>
                  <td><Link href={`/console/enrollments/${r.enrollment_id}`} className={s.mono}>{r.enrollment_id}</Link></td>
                  <td>{portal(r.target_form)}</td>
                  <td>{r.attempt}{r.retries_before ? <span className={s.subtle}> (after {r.retries_before} retr{r.retries_before === 1 ? "y" : "ies"})</span> : ""}</td>
                  <td>{r.path === "api" ? "API" : "web form"}{Object.keys(r.options).length ? <span className={s.subtle}> test: {Object.values(r.options).join(", ")}</span> : ""}</td>
                  <td>{r.status}</td>
                  <td className={s.num}>{r.duration_ms == null ? "–" : `${(r.duration_ms / 1000).toFixed(1)} s`}</td>
                  <td className={s.reasonCell}>{r.confirmation_ref ? <span className={s.mono}>{r.confirmation_ref}</span> : r.error_code ? `${r.error_code.replaceAll("_", " ").toLowerCase()}: ${r.error_detail ?? ""}` : "–"}</td>
                  <td className={s.hideSm}>{r.screenshots || "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </main>
    </>
  );
}
