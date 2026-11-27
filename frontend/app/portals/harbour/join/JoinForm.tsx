"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { type FieldError, todayUtc, type Values } from "@/lib/portals/common";
import { INTERESTS, MAX_START_DAYS, MEMBERSHIPS, REFERRALS, validateHarbour } from "@/lib/portals/harbour";
import s from "../harbour.module.css";

type Variant = "a" | "b";

const LABELS: Record<Variant, Record<string, string>> = {
  a: {
    full_name: "Full name", email: "Email", phone: "Phone", date_of_birth: "Date of birth", membership_type: "Membership",
    student_id: "Student card number", family_members: "People on the membership", start_date: "Start date", interests: "Interests",
    emergency_contact_name: "Emergency contact name", emergency_contact_phone: "Emergency contact phone",
    how_heard: "How did you hear about us?", accept_terms: "I accept the membership terms", submit: "Join the club",
    you: "About you", plan: "Your membership", emergency: "In an emergency", last: "Last thing",
  },
  b: {
    full_name: "Your name", email: "Email address", phone: "Mobile", date_of_birth: "Birthday", membership_type: "Plan",
    student_id: "Student ID card", family_members: "How many people?", start_date: "First day", interests: "What will you use?",
    emergency_contact_name: "Who should we call?", emergency_contact_phone: "Their number",
    how_heard: "Where did you find us?", accept_terms: "I agree to the club rules and membership terms", submit: "Become a member",
    you: "You", plan: "Plan", emergency: "Emergency contact", last: "Finally",
  },
};

const CHAOS_HEADER = ["slow", "flaky", "down", "lost"];
const isoDay = (d: Date) => d.toISOString().slice(0, 10);

export default function JoinForm({ variant, chaos }: { variant: Variant; chaos: string }) {
  const L = LABELS[variant];
  const today = useMemo(() => todayUtc(), []);
  const [values, setValues] = useState<Values>({ interests: [], accept_terms: false });
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [tried, setTried] = useState(false);
  const [banner, setBanner] = useState<{ kind: "error" | "notice"; text: string; tid: string } | null>(null);
  const [sending, setSending] = useState(false);
  const [human, setHuman] = useState(false);
  const [done, setDone] = useState<{ id: string; member: Values } | null>(null);
  const alertRef = useRef<HTMLDivElement>(null);
  const doneRef = useRef<HTMLHeadingElement>(null);

  const id = (n: string) => (variant === "a" ? `hsc-${n}` : `m_${n}`);
  const tid = (n: string) => (variant === "a" ? `hsc-${n.replaceAll("_", "-")}` : undefined);
  const err = (n: string) => errors.find((e) => e.field === n)?.message;
  const text = (n: string) => (typeof values[n] === "string" ? (values[n] as string) : "");
  const type = text("membership_type");

  const set = (n: string) => (v: unknown) => {
    const next = { ...values, [n]: v };
    setValues(next);
    if (tried) setErrors(validateHarbour(stripFor(next), today));
  };
  /** What is sent: conditional fields only when they apply, empty answers left out. */
  const stripFor = (v: Values): Values => {
    const out = { ...v };
    if (out.membership_type !== "student") delete out.student_id;
    if (out.membership_type !== "family") delete out.family_members;
    for (const [k, x] of Object.entries(out)) if (x === "") delete out[k];
    return out;
  };

  useEffect(() => { if (done) { window.scrollTo({ top: 0 }); doneRef.current?.focus(); } }, [done]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTried(true);
    setBanner(null);
    const body = stripFor(values);
    const local = validateHarbour(body, today);
    setErrors(local);
    if (local.length) { requestAnimationFrame(() => alertRef.current?.focus()); return; }
    setSending(true);
    try {
      const headers: Record<string, string> = { "content-type": "application/json" };
      if (CHAOS_HEADER.includes(chaos)) headers["x-portal-chaos"] = chaos;
      const res = await fetch("/api/portals/harbour/join", { method: "POST", headers, body: JSON.stringify(body) });
      const data = await res.json().catch(() => ({}));
      if (res.status === 201) { setDone({ id: data.member_id, member: data.member }); return; }
      if (res.status === 422 && Array.isArray(data.errors)) { setErrors(data.errors); requestAnimationFrame(() => alertRef.current?.focus()); return; }
      if (res.status === 409) { setBanner({ kind: "notice", tid: "hsc-duplicate", text: `You're already a member. Your member number is ${data.member_id}.` }); return; }
      setBanner({ kind: "error", tid: "hsc-submit-error", text: "Something went wrong on our side and you haven't been signed up yet. Try again in a minute." });
    } catch {
      setBanner({ kind: "error", tid: "hsc-submit-error", text: "We couldn't reach the club. Check your connection and try again." });
    } finally {
      setSending(false);
    }
  };

  const field = (n: string, input: React.ReactNode, opts: { hint?: string; full?: boolean } = {}) => (
    <div className={`${s.field} ${opts.full ? s.full : ""} ${err(n) ? s.invalid : ""}`}>
      <label className={s.label} htmlFor={id(n)}>{L[n]}</label>
      {opts.hint && <p className={s.hint} id={`${id(n)}-hint`}>{opts.hint}</p>}
      {err(n) && <p className={s.error} id={`${id(n)}-error`} data-testid={tid(n) ? `${tid(n)}-error` : undefined}>{err(n)}</p>}
      {input}
    </div>
  );
  const a11y = (n: string, hint = false) => ({
    id: id(n), name: n, "data-testid": tid(n), "aria-invalid": err(n) ? true : undefined,
    "aria-describedby": [hint ? `${id(n)}-hint` : "", err(n) ? `${id(n)}-error` : ""].filter(Boolean).join(" ") || undefined,
  });

  if (done) {
    const m = done.member;
    const rows: [string, string][] = [["full_name", "Name"], ["email", "Email"], ["phone", "Phone"], ["date_of_birth", "Date of birth"],
      ["membership_type", "Membership"], ["student_id", "Student card"], ["family_members", "People"], ["start_date", "Start date"],
      ["interests", "Interests"], ["emergency_contact_name", "Emergency contact"], ["emergency_contact_phone", "Emergency phone"]];
    return (
      <>
        <Band variant={variant} heading={false} />
        <div className={s.wrap} style={{ gridTemplateColumns: "minmax(0, 760px)" }}>
          <main className={s.done} data-testid="hsc-confirmation">
            <h1 ref={doneRef} tabIndex={-1}>Welcome to the club</h1>
            <p>Your member number</p>
            <p className={s.ref} data-testid="hsc-confirmation-ref">{done.id}</p>
            <p>Bring this number to reception on your first visit to collect your card.</p>
            <dl className={s.readback}>
              {rows.filter(([k]) => m[k] !== null && m[k] !== undefined).map(([k, label]) => (
                <div key={k} style={{ display: "contents" }}>
                  <dt>{label}</dt>
                  <dd data-testid={`hsc-confirm-${k.replaceAll("_", "-")}`} data-value={Array.isArray(m[k]) ? (m[k] as string[]).join(",") : String(m[k])}>
                    {Array.isArray(m[k]) ? (m[k] as string[]).join(", ") : String(m[k])}
                  </dd>
                </div>
              ))}
            </dl>
            <button type="button" className={s.again} onClick={() => { setDone(null); setValues({ interests: [], accept_terms: false }); setTried(false); setErrors([]); }}>Register someone else</button>
          </main>
        </div>
      </>
    );
  }

  const you = (
    <fieldset className={s.section} key="you">
      <legend className={s.sectionTitle}>{L.you}</legend>
      <div className={s.grid}>
        {field("full_name", <input className={s.input} autoComplete="name" spellCheck={false} value={text("full_name")} onChange={(e) => set("full_name")(e.target.value)} {...a11y("full_name")} />, { full: true })}
        {field("email", <input className={s.input} type="email" autoComplete="email" spellCheck={false} value={text("email")} onChange={(e) => set("email")(e.target.value)} {...a11y("email")} />)}
        {field("phone", <input className={s.input} type="tel" autoComplete="tel" value={text("phone")} onChange={(e) => set("phone")(e.target.value)} {...a11y("phone")} />)}
        {field("date_of_birth", <input className={s.input} type="date" autoComplete="bday" value={text("date_of_birth")} max={isoDay(today)} onChange={(e) => set("date_of_birth")(e.target.value)} {...a11y("date_of_birth", true)} />, { hint: "Members are 16 or older" })}
      </div>
    </fieldset>
  );

  const plan = (
    <fieldset className={s.section} key="plan">
      <legend className={s.sectionTitle}>{L.plan}</legend>
      <div className={s.grid}>
        {field("membership_type", (
          <select className={s.input} value={type} onChange={(e) => set("membership_type")(e.target.value)} {...a11y("membership_type", true)}>
            <option value="">Choose a membership</option>
            {MEMBERSHIPS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        ), { hint: MEMBERSHIPS.find((m) => m.value === type)?.note ?? "Adult, student, family or off-peak" })}
        {field("start_date", <input className={s.input} type="date" value={text("start_date")} min={isoDay(today)} max={isoDay(new Date(today.getTime() + MAX_START_DAYS * 86_400_000))} onChange={(e) => set("start_date")(e.target.value)} {...a11y("start_date", true)} />, { hint: `Within the next ${MAX_START_DAYS} days` })}
        {type === "student" && field("student_id", <input className={s.input} spellCheck={false} value={text("student_id")} onChange={(e) => set("student_id")(e.target.value)} {...a11y("student_id", true)} />, { hint: "6 to 12 letters or digits, as printed on your card" })}
        {type === "family" && field("family_members", <input className={s.input} type="number" min={2} max={6} inputMode="numeric" value={text("family_members")} onChange={(e) => set("family_members")(e.target.value)} {...a11y("family_members", true)} />, { hint: "Including you: 2 to 6" })}
        <fieldset className={`${s.field} ${s.full} ${err("interests") ? s.invalid : ""}`} data-testid={tid("interests")} aria-describedby={err("interests") ? `${id("interests")}-error` : undefined}>
          <legend className={s.label}>{L.interests}</legend>
          <p className={s.hint}>Pick everything you plan to use</p>
          {err("interests") && <p className={s.error} id={`${id("interests")}-error`} data-testid={tid("interests") ? `${tid("interests")}-error` : undefined}>{err("interests")}</p>}
          <div className={s.tiles}>
            {INTERESTS.map((i) => {
              const list = (values.interests as string[]) ?? [];
              return (
                <label key={i.value} className={s.tile}>
                  <input type="checkbox" name="interests" value={i.value} checked={list.includes(i.value)} id={`${id("interests")}-${i.value}`}
                    data-testid={tid("interests") ? `${tid("interests")}-${i.value}` : undefined}
                    onChange={(e) => set("interests")(e.target.checked ? [...list, i.value] : list.filter((x) => x !== i.value))} />
                  <span>{i.label}</span>
                </label>
              );
            })}
          </div>
        </fieldset>
      </div>
    </fieldset>
  );

  const emergency = (
    <fieldset className={s.section} key="emergency">
      <legend className={s.sectionTitle}>{L.emergency}</legend>
      <div className={s.grid}>
        {field("emergency_contact_name", <input className={s.input} spellCheck={false} value={text("emergency_contact_name")} onChange={(e) => set("emergency_contact_name")(e.target.value)} {...a11y("emergency_contact_name")} />)}
        {field("emergency_contact_phone", <input className={s.input} type="tel" value={text("emergency_contact_phone")} onChange={(e) => set("emergency_contact_phone")(e.target.value)} {...a11y("emergency_contact_phone", true)} />, { hint: "Not your own number" })}
      </div>
    </fieldset>
  );

  const order = variant === "a" ? [you, plan, emergency] : [you, emergency, plan];

  return (
    <>
      <Band variant={variant} />
      <div className={s.wrap}>
        <main>
          <form className={s.form} onSubmit={submit} noValidate>
            {tried && errors.length > 0 && (
              <div className={s.alert} role="alert" tabIndex={-1} ref={alertRef} data-testid={variant === "a" ? "hsc-error-summary" : undefined}>
                <strong>{errors.length === 1 ? "One thing needs fixing" : `${errors.length} things need fixing`}</strong> before you can join.
              </div>
            )}
            {order}
            <fieldset className={s.section}>
              <legend className={s.sectionTitle}>{L.last}</legend>
              {field("how_heard", (
                <select className={s.input} value={text("how_heard")} onChange={(e) => set("how_heard")(e.target.value)} {...a11y("how_heard")}>
                  <option value="">Prefer not to say</option>
                  {REFERRALS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
              ))}
              <div className={`${s.field} ${err("accept_terms") ? s.invalid : ""}`}>
                {err("accept_terms") && <p className={s.error} id={`${id("accept_terms")}-error`} data-testid={tid("accept_terms") ? `${tid("accept_terms")}-error` : undefined}>{err("accept_terms")}</p>}
                <label className={s.check}>
                  <input type="checkbox" checked={values.accept_terms === true} onChange={(e) => set("accept_terms")(e.target.checked)} {...a11y("accept_terms")} />
                  <span>{L.accept_terms}</span>
                </label>
              </div>
              {chaos === "captcha" && (
                <section className={s.captcha} aria-label="Security check" data-testid="captcha">
                  <p className={s.label}>Security check</p>
                  <label className={s.check}><input type="checkbox" checked={human} onChange={(e) => setHuman(e.target.checked)} /> <span>I am not a robot</span></label>
                </section>
              )}
            </fieldset>
            {banner && <div className={banner.kind === "error" ? s.alert : s.notice} role="alert" data-testid={banner.tid}>{banner.text}</div>}
            <button type="submit" className={s.submit} disabled={sending || (chaos === "captcha" && !human)} aria-busy={sending} data-testid={variant === "a" ? "hsc-submit" : undefined}>
              {sending ? "Signing you up…" : L.submit}
            </button>
          </form>
        </main>
        <aside className={s.aside} aria-labelledby="hsc-facilities">
          <h2 id="hsc-facilities">At the club</h2>
          <dl>
            <dt>25 m pool</dt><dd>Lane swimming from 6am, lessons at weekends.</dd>
            <dt>Courts</dt><dd>Four tennis and two squash courts, bookable a week ahead.</dd>
            <dt>Wall</dt><dd>A 12 m climbing wall with taught sessions for beginners.</dd>
            <dt>Studio</dt><dd>Yoga, spin and strength classes most evenings.</dd>
          </dl>
        </aside>
      </div>
    </>
  );
}

function Band({ variant, heading = true }: { variant: Variant; heading?: boolean }) {
  const Title = heading ? "h1" : "p";
  return (
    <>
      <header className={s.band}>
        <div className={s.bandInner}>
          <div className={s.nav}>
            <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true"><circle cx="14" cy="14" r="12" fill="none" stroke="#f5c518" strokeWidth="4" /><circle cx="14" cy="14" r="4" fill="#f5c518" /></svg>
            Harbour Sports Club
          </div>
          <Title className={s.headline}>{variant === "a" ? "Join Harbour Sports Club" : "Become a member"}</Title>
          <p className={s.sub}>Pool, courts, climbing wall and studio on the waterfront. Sign up in a few minutes and start within the next three months.</p>
        </div>
      </header>
      <div className={s.rope} aria-hidden="true" />
    </>
  );
}
