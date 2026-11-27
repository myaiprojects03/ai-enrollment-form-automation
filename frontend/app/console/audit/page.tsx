"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type AuditEntry } from "@/lib/console/api";
import { ACTIONS, describeDetails } from "@/lib/console/audit";
import s from "../console.module.css";
import TopBar from "../TopBar";

export default function AuditLog() {
  const [rows, setRows] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api<AuditEntry[]>("audit?limit=300").then(setRows).catch((e) => setError((e as Error).message)); }, []);
  return (
    <>
      <TopBar active="audit" />
      <main className={s.page}>
        <div className={s.pageHead}>
          <div>
            <h1 className={s.title}>Audit log</h1>
            <p className={s.subtle}>Every sign-in, edit, decision and submission, newest first. Personal data is never written here.</p>
          </div>
        </div>
        {error && <p className={s.errorBox} role="alert">{error}</p>}
        {rows && (
          <table className={s.table} data-testid="audit-table">
            <thead><tr><th>When</th><th>Who</th><th>What</th><th>Enrollment</th><th className={s.hideSm}>Details</th></tr></thead>
            <tbody>
              {rows.map((a, i) => (
                <tr key={i}>
                  <td className={s.num} style={{ textAlign: "left", whiteSpace: "nowrap" }}>{new Date(a.at).toLocaleString("en-GB")}</td>
                  <td>{a.actor}</td>
                  <td>{ACTIONS[a.action] ?? a.action}</td>
                  <td>{a.enrollment_id ? <Link href={`/console/enrollments/${a.enrollment_id}`} className={s.mono}>{a.enrollment_id}</Link> : "–"}</td>
                  <td className={`${s.reasonCell} ${s.hideSm}`}>{describeDetails(a.details)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </main>
    </>
  );
}
