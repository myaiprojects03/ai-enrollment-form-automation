"use client";
import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ago, api, type Detail, type Field, type Form, type FormField, type Reason, type Run, STATUS_LABEL,
} from "@/lib/console/api";
import { ACTIONS, describeDetails } from "@/lib/console/audit";
import s from "../../console.module.css";
import TopBar from "../../TopBar";

const THRESHOLD = 0.85;
const METHOD: Record<string, string> = { rule: "rule", derived: "derived", llm: "AI", default: "default", edited: "edited", none: "" };
const SEVERITY_WORD: Record<string, string> = { block: "Blocked", review: "Review", info: "Note" };
type SideTab = "source" | "screenshots" | "runs" | "audit";

export default function EnrollmentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [edits, setEdits] = useState<Record<string, unknown>>({});
  const [side, setSide] = useState<SideTab>("source");
  const [busy, setBusy] = useState("");
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");
  const rejectDialog = useRef<HTMLDialogElement>(null);
  const [rejectNote, setRejectNote] = useState("");

  const load = useCallback(async () => {
    try {
      const [d, r] = await Promise.all([api<Detail>(`enrollments/${id}?reveal=true`), api<Run[]>(`enrollments/${id}/runs`)]);
      setDetail(d);
      setRuns(r);
      setError("");
      return d;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, [id]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!detail || form) return;
    api<Form[]>("forms").then((all) => setForm(all.find((f) => f.id === detail.target_form) ?? null)).catch(() => undefined);
  }, [detail, form]);
  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(""), 6000); return () => clearTimeout(t); }, [toast]);

  const flags = useMemo(() => {
    const out: Record<string, "block" | "review"> = {};
    for (const r of detail?.reasons ?? []) {
      if (!r.field || r.severity === "info") continue;
      if (r.severity === "block" || !out[r.field]) out[r.field] = r.severity;
    }
    return out;
  }, [detail]);

  if (!detail) {
    return (<><TopBar active="queue" /><main className={s.page}>{error ? <p className={s.errorBox} role="alert">{error}</p> : <p className={s.subtle}>Loading…</p>}</main></>);
  }

  const locked = ["submitting", "submitted", "rejected"].includes(detail.status);
  const dirty = Object.keys(edits).length > 0;
  const blocking = detail.reasons.filter((r) => r.severity === "block").length;
  const value = (f: Field) => (f.field in edits ? edits[f.field] : f.value);

  const act = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    try { await fn(); } catch (e) { setToast((e as Error).message); } finally { setBusy(""); }
  };

  const save = () => act("save", async () => {
    await api(`enrollments/${id}/fields`, { method: "PATCH", json: { changes: edits } });
    setEdits({});
    const d = await load();
    setToast(d ? `Saved. The record is now ${d.outcome?.replace("_", " ").toLowerCase()}.` : "Saved.");
  });

  const remap = () => act("remap", async () => {
    await api(`enrollments/${id}/process`, { method: "POST" });
    await load();
    setToast("Mapped again from the source. Your edits were kept.");
  });

  const waitForSubmission = async () => {
    for (let i = 0; i < 120; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      // Poll without revealing personal data (each reveal is an audited view); reload fully once it is done.
      const brief = await api<Detail>(`enrollments/${id}`).catch(() => null);
      if (!brief || ["approved", "submitting"].includes(brief.status)) continue;
      const d = await load();
      if (d) {
        setSide("screenshots");
        setToast(d.status === "submitted" ? `Submitted. Portal reference ${d.confirmation_ref}.`
          : `Not submitted: ${d.reasons[0]?.message ?? STATUS_LABEL[d.status]}`);
        return;
      }
    }
    setToast("Still submitting. Check back in a minute.");
  };

  const approveAndSubmit = () => act("submit", async () => {
    if (detail.status !== "approved") await api(`enrollments/${id}/approve`, { method: "POST", json: { note: "" } });
    await api(`enrollments/${id}/submit`, { method: "POST", json: {} });
    await load();
    await waitForSubmission();
  });

  const reject = () => act("reject", async () => {
    await api(`enrollments/${id}/reject`, { method: "POST", json: { note: rejectNote } });
    rejectDialog.current?.close();
    setRejectNote("");
    await load();
    setToast("Rejected. It will not be submitted.");
  });

  const specs = new Map((form?.fields ?? []).map((f) => [f.name, f]));
  const canApprove = !locked && blocking === 0 && !dirty;

  return (
    <>
      <TopBar active="queue" />
      <main className={s.page}>
        <p style={{ margin: "0 0 8px" }}><Link href="/console">Back to the queue</Link></p>
        <div className={s.detailHead}>
          <h1 className={`${s.title} ${s.mono}`} data-testid="enrollment-id">{detail.enrollment_id}</h1>
          {detail.outcome && <span className={`${s.pill} ${s[detail.outcome]}`} data-testid="outcome"
            title={detail.reasons.some((r) => r.accepted_by) ? "Outcome of the automatic check; a reviewer accepted the open points" : undefined}>
            {detail.outcome.replace("_", " ")}{detail.reasons.some((r) => r.accepted_by) ? ", accepted" : ""}</span>}
          <span className={`${s.pill} ${s.status}`} data-testid="status">{STATUS_LABEL[detail.status] ?? detail.status}</span>
          <div className={s.actions}>
            {!locked && <button type="button" className={s.btn} onClick={remap} disabled={busy !== ""}>{busy === "remap" ? "Mapping…" : "Map again"}</button>}
            {!locked && <button type="button" className={`${s.btn} ${s.danger}`} onClick={() => rejectDialog.current?.showModal()} disabled={busy !== ""}>Reject</button>}
            {!locked && (
              <button type="button" className={`${s.btn} ${s.primary}`} onClick={approveAndSubmit} disabled={!canApprove || busy !== ""}
                title={blocking ? "Fix the blocking problems first" : dirty ? "Save your changes first" : undefined} data-testid="approve-submit">
                {busy === "submit" ? "Submitting…" : detail.status === "approved" ? "Submit now" : "Approve & submit"}
              </button>
            )}
            {detail.status === "submitting" && <span className={s.subtle}>Submitting to the portal…</span>}
          </div>
        </div>
        <div className={s.meta}>
          <span>{form?.portal ?? detail.target_form}</span>
          <span>From {detail.source}</span>
          <span>Mapped by {detail.mapper?.replace("rules+", "rules and ") ?? "–"}</span>
          {detail.confirmation_ref && <span>Portal reference <b className={s.mono} data-testid="confirmation-ref">{detail.confirmation_ref}</b> ({detail.submit_path})</span>}
          <span>Updated {ago(detail.updated_at)}</span>
        </div>
        {error && <p className={s.errorBox} role="alert">{error}</p>}

        <div className={s.split}>
          <section aria-label="Fields">
            <Reasons reasons={detail.reasons} />
            <div className={s.fields} data-testid="fields">
              {detail.fields.map((f) => (
                <FieldRow key={f.field} field={f} spec={specs.get(f.field)} need={need(specs.get(f.field), specs)} value={value(f)} flag={flags[f.field]} locked={locked}
                  dirty={f.field in edits} onChange={(v) => setEdits((old) => ({ ...old, [f.field]: v }))} />
              ))}
            </div>
            {dirty && (
              <div className={s.saveBar}>
                <span>{Object.keys(edits).length} field{Object.keys(edits).length === 1 ? "" : "s"} changed.</span>
                <button type="button" className={`${s.btn} ${s.primary}`} onClick={save} disabled={busy !== ""} data-testid="save">{busy === "save" ? "Saving…" : "Save and check again"}</button>
                <button type="button" className={s.btn} onClick={() => setEdits({})}>Discard</button>
              </div>
            )}
          </section>

          <aside className={s.side} aria-label="Evidence">
            <div className={s.sideTabs} role="tablist">
              {(["source", "screenshots", "runs", "audit"] as SideTab[]).map((t) => (
                <button key={t} type="button" role="tab" className={s.tab} aria-selected={side === t} onClick={() => setSide(t)} data-testid={`side-${t}`}>
                  {{ source: "Source record", screenshots: "Screenshots", runs: `Attempts (${runs.length})`, audit: "History" }[t]}
                </button>
              ))}
            </div>
            <div className={s.sideBody}>
              {side === "source" && <Source detail={detail} />}
              {side === "screenshots" && <Screenshots runs={runs} />}
              {side === "runs" && <Runs runs={runs} />}
              {side === "audit" && <Audit entries={detail.audit} />}
            </div>
          </aside>
        </div>

        <dialog ref={rejectDialog} className={s.dialog} aria-labelledby="reject-title">
          <h2 id="reject-title" className={s.panelTitle}>Reject this enrollment?</h2>
          <p className={s.subtle}>It will not be submitted. Say why for the history (no personal details needed).</p>
          <textarea className={`${s.input} ${s.notes}`} aria-label="Reason" value={rejectNote} onChange={(e) => setRejectNote(e.target.value)} />
          <div className={s.panelRow}>
            <button type="button" className={`${s.btn} ${s.danger}`} onClick={reject} disabled={busy !== ""} data-testid="confirm-reject">Reject</button>
            <button type="button" className={s.btn} onClick={() => rejectDialog.current?.close()}>Cancel</button>
          </div>
        </dialog>
        {toast && <div className={s.toast} role="status" data-testid="toast">{toast}</div>}
      </main>
    </>
  );
}

function Reasons({ reasons }: { reasons: Reason[] }) {
  if (!reasons.length) return <p className={s.subtle} style={{ margin: "0 0 14px" }}>Every rule is met and every field is above {THRESHOLD * 100}% confidence.</p>;
  const open = reasons.filter((r) => r.severity !== "info");
  const notes = reasons.filter((r) => r.severity === "info");
  return (
    <ul className={s.reasons} data-testid="reasons">
      {open.map((r, i) => (
        <li key={i} className={`${s.reason} ${s[`sev-${r.accepted_by ? "info" : r.severity}`]}`}>
          <b>{r.accepted_by ? "Accepted" : SEVERITY_WORD[r.severity]}</b>
          <span>{r.message}{r.accepted_by && <span className={s.subtle}> Accepted by {r.accepted_by} at approval.</span>}</span>
        </li>
      ))}
      {notes.length > 0 && (
        <li className={`${s.reason} ${s["sev-info"]}`}>
          <b>{notes.length === 1 ? "Note" : "Notes"}</b>
          <details>
            <summary>{notes.length === 1 ? notes[0].message : `${notes.length} notes about how fields were mapped`}</summary>
            {notes.length > 1 && <ul className={s.stepList}>{notes.map((r, i) => <li key={i}>{r.message}</li>)}</ul>}
          </details>
        </li>
      )}
    </ul>
  );
}

/** "Required", "Optional", or when a conditional field is needed ("Required for Student"). */
function need(spec: FormField | undefined, specs: Map<string, FormField>): string {
  if (!spec) return "";
  if (!spec.required) return "Optional";
  const when = spec.when;
  if (!when) return "Required";
  if (when.field === "date_of_birth") return "Required for under-18s";
  const basis = specs.get(when.field);
  if (basis?.type === "checkbox") return `Required if "${basis.label}" is ticked`;
  const labels = when.values.map((v) => basis?.options.find((o) => o.value === v)?.label ?? String(v));
  return `Required for ${labels.join(" or ")}`;
}

function FieldRow({ field, spec, need, value, flag, locked, dirty, onChange }: {
  field: Field; spec?: FormField; need: string; value: unknown; flag?: "block" | "review"; locked: boolean; dirty: boolean; onChange: (v: unknown) => void;
}) {
  const id = `f-${field.field}`;
  const resolved = field.state !== "unmapped";
  const pct = Math.round(field.confidence * 100);
  return (
    <div className={s.fieldRow} data-flag={flag} data-dirty={dirty} data-field={field.field}>
      <label className={s.fieldLabel} htmlFor={id}>
        {field.label}
        <small>{need || (field.required ? "Required" : "Optional")}{field.state === "ambiguous" ? ", more than one possible answer" : ""}</small>
      </label>
      <div>
        <Input id={id} spec={spec} value={value} disabled={locked} onChange={onChange} />
        {field.assumption && !dirty && <p className={s.fieldNote}>{field.assumption}</p>}
        {field.candidates.length > 0 && !dirty && <p className={s.fieldNote}>Other candidates: {field.candidates.join(", ")}</p>}
      </div>
      <div className={s.conf} aria-label={dirty ? "Edited" : resolved ? `${pct}% confidence` : "Not found in the source"}>
        <div className={s.meter} style={{ ["--threshold" as string]: `${THRESHOLD * 100}%` }}>
          <span className={dirty ? s.hi : !resolved ? s.none : field.confidence >= THRESHOLD ? s.hi : s.lo} style={{ width: dirty ? "100%" : `${resolved ? pct : 0}%` }} />
        </div>
        <div className={s.confLine}>
          <span>{dirty ? "edited" : resolved ? `${pct}%` : "not found"}</span>
          <span>{dirty ? "" : METHOD[field.method]}</span>
        </div>
        {!dirty && field.source_fields.length > 0 && <span title="Source column">{field.source_fields.join(", ")}</span>}
      </div>
    </div>
  );
}

function Input({ id, spec, value, disabled, onChange }: { id: string; spec?: FormField; value: unknown; disabled: boolean; onChange: (v: unknown) => void }) {
  const type = spec?.type ?? "text";
  if (type === "checkbox") {
    return <label className={s.check}><input id={id} type="checkbox" checked={value === true} disabled={disabled} onChange={(e) => onChange(e.target.checked)} /> {value === true ? "Yes" : "No"}</label>;
  }
  if (type === "multiselect") {
    const list = Array.isArray(value) ? (value as string[]) : [];
    return (
      <div className={s.checks} id={id} role="group">
        {spec?.options.map((o) => (
          <label key={o.value}><input type="checkbox" disabled={disabled} checked={list.includes(o.value)}
            onChange={(e) => onChange(e.target.checked ? [...list, o.value] : list.filter((x) => x !== o.value))} /> {o.label}</label>
        ))}
      </div>
    );
  }
  if (spec && spec.options.length > 0) {
    return (
      <select id={id} className={`${s.select} ${s.fieldInput}`} value={typeof value === "string" ? value : ""} disabled={disabled}
        onChange={(e) => onChange(e.target.value || null)}>
        <option value="">Not set</option>
        {spec.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  }
  const text = value === null || value === undefined ? "" : String(value);
  return (
    <input id={id} className={`${s.input} ${s.fieldInput}`} type={type === "date" ? "date" : type === "number" ? "number" : type === "email" ? "email" : "text"}
      value={text} disabled={disabled} onChange={(e) => onChange(type === "number" && e.target.value ? Number(e.target.value) : e.target.value)} />
  );
}

function Source({ detail }: { detail: Detail }) {
  const record = detail.source_record ?? {};
  const { notes, ...rest } = record as { notes?: unknown } & Record<string, unknown>;
  const unused = detail.mapping.unused_source_fields ?? [];
  return (
    <div data-testid="source">
      <p className={s.subtle} style={{ marginTop: 0 }}>Exactly as received{detail.source === "notes" || notes ? " (free text, read by the AI mapper)" : ""}.</p>
      {typeof notes === "string" && <pre className={s.notesText}>{notes}</pre>}
      {Object.keys(rest).length > 0 && (
        <dl className={s.kv}>
          {Object.entries(rest).map(([k, v]) => (
            <div key={k} style={{ display: "contents" }}>
              <dt>{k}{unused.includes(k) ? " (not used)" : ""}</dt>
              <dd>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {detail.mapping.llm_error && <p className={s.fieldNote}>AI mapper: {detail.mapping.llm_error}.</p>}
    </div>
  );
}

function Screenshots({ runs }: { runs: Run[] }) {
  const withShots = [...runs].reverse().filter((r) => r.screenshots.length);
  const [runId, setRunId] = useState(withShots[0]?.run_id ?? "");
  const run = withShots.find((r) => r.run_id === runId) ?? withShots[0];
  const [shotId, setShotId] = useState<number | null>(null);
  if (!run) return <p className={s.subtle}>No screenshots yet. Submissions through the portal&apos;s web form take them page by page.</p>;
  const shot = run.screenshots.find((x) => x.id === shotId) ?? run.screenshots[run.screenshots.length - 1];
  return (
    <div data-testid="screenshots">
      {withShots.length > 1 && (
        <select className={s.select} aria-label="Attempt" value={run.run_id} onChange={(e) => { setRunId(e.target.value); setShotId(null); }} style={{ marginBottom: 10 }}>
          {withShots.map((r) => <option key={r.run_id} value={r.run_id}>Attempt {r.attempt}, {r.status}</option>)}
        </select>
      )}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className={s.shotMain} src={`/api/console/engine/runs/${run.run_id}/screenshots/${shot.id}`} alt={`Portal page: ${shot.label}`} />
      <div className={s.thumbs}>
        {run.screenshots.map((x) => (
          <button key={x.id} type="button" className={s.thumb} aria-pressed={x.id === shot.id} onClick={() => setShotId(x.id)}>{x.label}</button>
        ))}
      </div>
      <p className={s.fieldNote}>Screenshots are stored encrypted. Viewing them is recorded in the history.</p>
    </div>
  );
}

function Runs({ runs }: { runs: Run[] }) {
  if (!runs.length) return <p className={s.subtle}>Not submitted yet.</p>;
  return (
    <ol className={s.timeline} data-testid="runs">
      {[...runs].reverse().map((r) => (
        <li key={r.run_id} data-ok={r.status === "succeeded" ? "true" : r.status === "running" ? undefined : "false"}>
          <b>Attempt {r.attempt}</b>, {r.path === "api" ? "portal API" : "web form"}: {r.status}
          {r.duration_ms != null && <span className={s.subtle}> in {(r.duration_ms / 1000).toFixed(1)} s</span>}
          {r.confirmation_ref && <div>Reference <span className={s.mono}>{r.confirmation_ref}</span></div>}
          {r.error_code && <div className={s.danger}>{r.error_code.replaceAll("_", " ").toLowerCase()}: {r.error_detail}</div>}
          {Object.keys(r.options).length > 0 && <div className={s.subtle}>Test mode: {Object.entries(r.options).map(([k, v]) => `${k} ${v}`).join(", ")}</div>}
          <ul className={s.stepList}>
            {r.steps.map((st, i) => <li key={i}>{describeStep(st)}</li>)}
          </ul>
          <div className={s.subtle}>{new Date(r.started_at).toLocaleString("en-GB")} by {r.actor}</div>
        </li>
      ))}
    </ol>
  );
}

function describeStep(st: Record<string, unknown>): string {
  if (typeof st.lookup === "string") return `Portal checked: ${st.lookup}`;
  if (typeof st.api === "string") return `Portal API ${st.api} answered ${st.status}`;
  const filled = Array.isArray(st.filled) ? st.filled.length : 0;
  const locators = (st.locators ?? {}) as Record<string, string>;
  const healed = Object.values(locators).filter((v) => !v.startsWith("testid:")).length;
  const result = { moved: "next page", confirmation: "confirmation", banner: "portal error", errors: "field errors", duplicate: "already received", stuck: "no response" }[String(st.result)] ?? "";
  const checked = typeof st.verified === "number" ? `, ${st.verified} read back and matched` : "";
  return `Page ${st.page}${st.heading ? ` "${st.heading}"` : ""}: ${filled} field${filled === 1 ? "" : "s"} filled${checked}${healed ? `, ${healed} found without a test id` : ""}${result ? `, then ${result}` : ""}`;
}

function Audit({ entries }: { entries: { actor: string; action: string; details: Record<string, unknown>; at: string }[] }) {
  return (
    <ul className={s.auditList} data-testid="audit">
      {[...entries].reverse().map((a, i) => (
        <li key={i}>
          <time dateTime={a.at}>{new Date(a.at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</time>
          <span><b>{ACTIONS[a.action] ?? a.action}</b> by {a.actor}{describeDetails(a.details) ? `: ${describeDetails(a.details)}` : ""}</span>
        </li>
      ))}
    </ul>
  );
}
