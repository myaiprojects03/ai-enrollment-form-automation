"use client";
import { useState } from "react";
import s from "../console.module.css";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    const res = await fetch("/api/console/login", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email, password }),
    }).catch(() => null);
    setBusy(false);
    if (!res) return setError("Could not reach the console. Check your connection.");
    if (!res.ok) return setError((await res.json().catch(() => ({}))).error ?? "Sign-in failed.");
    const next = new URLSearchParams(window.location.search).get("next");
    window.location.href = next && next.startsWith("/console") ? next : "/console";
  };

  return (
    <main className={s.login}>
      <form className={s.loginBox} onSubmit={submit}>
        <h1>Enrollment desk</h1>
        <p className={s.subtle}>Sign in to review and submit enrollments.</p>
        {error && <p className={s.errorBox} role="alert" style={{ marginTop: 14 }} data-testid="login-error">{error}</p>}
        <label htmlFor="email">Email</label>
        <input id="email" className={s.input} type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <label htmlFor="password">Password</label>
        <input id="password" className={s.input} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <button type="submit" className={`${s.btn} ${s.primary}`} disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </main>
  );
}
