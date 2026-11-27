"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/console/api";
import s from "./console.module.css";

export default function TopBar({ active }: { active: "queue" | "runs" | "audit" | "" }) {
  const [who, setWho] = useState("");
  useEffect(() => { api<{ actor: string }>("auth/me").then((r) => setWho(r.actor)).catch(() => setWho("")); }, []);
  const signOut = async () => {
    await fetch("/api/console/logout", { method: "POST" });
    window.location.href = "/console/login";
  };
  return (
    <header className={s.bar}>
      <div className={s.barInner}>
        <Link href="/console" className={s.product}>Enrollment desk</Link>
        <nav className={s.nav} aria-label="Console">
          <Link href="/console" aria-current={active === "queue" ? "page" : undefined}>Queue</Link>
          <Link href="/console/runs" aria-current={active === "runs" ? "page" : undefined}>Run history</Link>
          <Link href="/console/audit" aria-current={active === "audit" ? "page" : undefined}>Audit log</Link>
        </nav>
        <div className={s.who}>
          <span className={s.hideSm} data-testid="console-user">{who}</span>
          <button type="button" className={s.linkButton} onClick={signOut}>Sign out</button>
        </div>
      </div>
    </header>
  );
}
