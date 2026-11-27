"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { type FieldError, forFields, todayUtc, ukToIso, type Values } from "@/lib/portals/common";
import {
  isMinor, MODES, modeLabel, PROGRAMMES, programmeLabel, RELATIONSHIPS, relationshipLabel, STEP_FIELDS, type StepId,
  TERMS, termLabel, validateRiverside,
} from "@/lib/portals/riverside";
import s from "../riverside.module.css";
import { CheckField, Combobox, DateField, RadioGroup, SelectField, TextField } from "./controls";

type Variant = "a" | "b";

const STEP_NAMES: Record<StepId, string> = { student: "Student", guardian: "Guardian", course: "Course", address: "Address", review: "Review" };
const ORDER: Record<Variant, StepId[]> = {
  a: ["student", "guardian", "course", "address", "review"],
  b: ["student", "guardian", "address", "course", "review"],   // layout drift: two steps swapped
};
const HEADINGS: Record<StepId, [string, string]> = {
  student: ["About the student", "Tell us who is applying. We use these details to contact you about the application."],
  guardian: ["Parent or guardian", "Students under 18 need a parent or guardian to support their application."],
  course: ["Your course", "Choose what you would like to study and when you would like to start."],
  address: ["Home address", "Where the student lives during term time."],
  review: ["Check your answers", "Make sure everything is right before you submit the application."],
};

/** Variant b rewords labels and buttons, the way a real site changes between visits. */
const LABELS: Record<Variant, Record<string, string>> = {
  a: {
    first_name: "First name", last_name: "Last name", date_of_birth: "Date of birth", email: "Email address", phone: "Mobile number",
    guardian_name: "Guardian's full name", guardian_relationship: "Relationship to student", guardian_phone: "Guardian's mobile number",
    guardian_email: "Guardian's email (optional)", program: "Programme", start_term: "Start term", study_mode: "Study mode",
    prior_enrollment: "I have studied at Riverside Academy before", prior_student_id: "Previous student ID",
    address_line1: "Address line 1", address_line2: "Address line 2 (optional)", city: "Town or city", postcode: "Postcode",
    consent_terms: "I agree to the enrollment terms", marketing_opt_in: "Send me news about courses and events",
    next: "Continue", back: "Back", submit: "Submit application",
  },
  b: {
    first_name: "Given name", last_name: "Family name", date_of_birth: "Birth date", email: "Email", phone: "Mobile phone",
    guardian_name: "Name of parent or guardian", guardian_relationship: "How are they related to the student?",
    guardian_phone: "Parent or guardian mobile", guardian_email: "Parent or guardian email (optional)", program: "Course",
    start_term: "When would you like to start?", study_mode: "How will you study?",
    prior_enrollment: "I am a returning student", prior_student_id: "Student number from your last course",
    address_line1: "House number and street", address_line2: "Flat, building or area (optional)", city: "Town", postcode: "Post code",
    consent_terms: "I accept the terms of enrollment", marketing_opt_in: "Keep me updated about new courses",
    next: "Next step", back: "Previous", submit: "Send application",
  },
};

const CHAOS_HEADER = ["slow", "flaky", "down", "lost"];

type Done = { ref: string; application: Values };

export default function Wizard({ variant, chaos }: { variant: Variant; chaos: string }) {
  const L = LABELS[variant];
  const today = useMemo(() => todayUtc(), []);
  const [values, setValues] = useState<Values>({ prior_enrollment: false, consent_terms: false, marketing_opt_in: false });
  const [dobText, setDobText] = useState("");
  const [step, setStep] = useState<StepId>("student");
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [banner, setBanner] = useState<{ kind: "error" | "notice"; text: string; tid: string } | null>(null);
  const [sending, setSending] = useState(false);
  const [human, setHuman] = useState(false);
  const [done, setDone] = useState<Done | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const summary = useRef<HTMLDivElement>(null);
  const firstRender = useRef(true);

  const id = (name: string) => (variant === "a" ? `f-${name}` : `rv_${name}_input`);
  const tid = (name: string) => (variant === "a" ? `ra-${name.replaceAll("_", "-")}` : undefined);
  const btn = (name: string) => (variant === "a" ? `ra-${name}` : undefined);
  const err = (name: string) => errors.find((e) => e.field === name)?.message;
  const set = (name: string) => (v: unknown) => setValues((old) => ({ ...old, [name]: v }));
  const text = (name: string) => (typeof values[name] === "string" ? (values[name] as string) : "");

  const dobIso = ukToIso(dobText);
  const minor = isMinor(dobIso, today);
  const steps = ORDER[variant].filter((st) => st !== "guardian" || minor === true);
  const position = steps.indexOf(step);

  const payload = (): Values => {
    const out: Values = { ...values, date_of_birth: dobIso || (dobText.trim() ? dobText.trim() : "") };
    if (minor !== true) for (const k of STEP_FIELDS.guardian) delete out[k];
    if (out.prior_enrollment !== true) delete out.prior_student_id;
    for (const [k, v] of Object.entries(out)) if (v === "") delete out[k];
    return out;
  };

  useEffect(() => {
    if (firstRender.current) { firstRender.current = false; return; }
    window.scrollTo({ top: 0 });
    heading.current?.focus();
  }, [step, done]);

  useEffect(() => { if (errors.length) summary.current?.focus(); }, [errors]);

  const showErrors = (list: FieldError[]) => { setErrors(list); setBanner(null); };

  const next = () => {
    const found = forFields(validateRiverside(payload(), today), STEP_FIELDS[step]);
    if (found.length) return showErrors(found);
    setErrors([]);
    setStep(steps[position + 1]);
  };

  const back = () => { setErrors([]); setBanner(null); setStep(steps[Math.max(position - 1, 0)]); };

  const goToStepOf = (list: FieldError[]) => {
    const target = steps.find((st) => list.some((e) => STEP_FIELDS[st].includes(e.field))) ?? "review";
    setStep(target);
    showErrors(list.filter((e) => STEP_FIELDS[target].includes(e.field) || target === "review"));
  };

  const submit = async () => {
    const body = payload();
    const local = validateRiverside(body, today);
    if (local.length) return goToStepOf(local);
    setSending(true);
    setBanner(null);
    try {
      const headers: Record<string, string> = { "content-type": "application/json" };
      if (CHAOS_HEADER.includes(chaos)) headers["x-portal-chaos"] = chaos;
      const res = await fetch("/api/portals/riverside/applications", { method: "POST", headers, body: JSON.stringify(body) });
      const data = await res.json().catch(() => ({}));
      if (res.status === 201) { setErrors([]); setDone({ ref: data.ref, application: data.application }); return; }
      if (res.status === 422 && Array.isArray(data.errors)) return goToStepOf(data.errors);
      if (res.status === 409) {
        setBanner({ kind: "notice", tid: "ra-duplicate", text: `We already have this application. Your reference is ${data.ref}.` });
        return;
      }
      setBanner({ kind: "error", tid: "ra-submit-error", text: "We could not submit your application. Wait a moment and try again." });
    } catch {
      setBanner({ kind: "error", tid: "ra-submit-error", text: "We could not reach Riverside Academy. Check your connection and try again." });
    } finally {
      setSending(false);
    }
  };

  if (done) return <Confirmation done={done} onRestart={() => { setDone(null); setValues({ prior_enrollment: false, consent_terms: false, marketing_opt_in: false }); setDobText(""); setStep("student"); }} headingRef={heading} />;

  const [title, lede] = HEADINGS[step];
  const latestYear = today.getUTCFullYear() - 14;

  return (
    <div className={s.shell}>
      <nav className={s.rail} aria-label="Application progress">
        <ol>
          {ORDER[variant].map((st) => {
            const skipped = st === "guardian" && minor === false;
            const idx = steps.indexOf(st);
            const cls = st === step ? s.railCurrent : skipped ? s.railSkipped : idx >= 0 && idx < position ? s.railDone : "";
            return (
              <li key={st} className={`${s.railItem} ${cls}`} aria-current={st === step ? "step" : undefined}>
                <span className={s.dot} aria-hidden="true">{idx >= 0 && idx < position && !skipped ? "✓" : ""}</span>
                <span>{STEP_NAMES[st]}{skipped && <span className={s.railNote}>Not needed (18 or over)</span>}</span>
              </li>
            );
          })}
        </ol>
      </nav>

      <main className={s.panel} data-step={step}>
        <p className={s.stepCount}>Step {position + 1} of {steps.length}</p>
        <h1 className={s.title} ref={heading} tabIndex={-1}>{title}</h1>
        <p className={s.lede}>{lede}</p>

        {errors.length > 0 && (
          <div className={s.summary} role="alert" tabIndex={-1} ref={summary} data-testid={variant === "a" ? "ra-error-summary" : undefined}>
            <h2>There is a problem</h2>
            <ul>
              {errors.map((e) => (
                <li key={e.field + e.message}>
                  <a href={`#${id(e.field)}`} onClick={(ev) => { ev.preventDefault(); document.getElementById(id(e.field))?.focus(); }}>{e.message}</a>
                </li>
              ))}
            </ul>
          </div>
        )}
        {banner && <div className={banner.kind === "error" ? s.banner : s.notice} role="alert" data-testid={banner.tid}>{banner.text}</div>}

        <form noValidate onSubmit={(e) => { e.preventDefault(); if (step === "review") void submit(); else next(); }}>
          {step === "student" && (
            <>
              <TextField id={id("first_name")} name="first_name" label={L.first_name} tid={tid("first_name")} error={err("first_name")} value={text("first_name")} onChange={set("first_name")} autoComplete="given-name" spellCheck={false} />
              <TextField id={id("last_name")} name="last_name" label={L.last_name} tid={tid("last_name")} error={err("last_name")} value={text("last_name")} onChange={set("last_name")} autoComplete="family-name" spellCheck={false} />
              <DateField id={id("date_of_birth")} name="date_of_birth" label={L.date_of_birth} hint="For example, 27/03/2007" tid={tid("date_of_birth")} error={err("date_of_birth")}
                value={dobText} onChange={setDobText} earliest={today.getUTCFullYear() - 99} latest={latestYear} startYear={latestYear - 4} />
              <TextField id={id("email")} name="email" type="email" label={L.email} tid={tid("email")} error={err("email")} value={text("email")} onChange={set("email")} autoComplete="email" spellCheck={false} />
              <TextField id={id("phone")} name="phone" type="tel" label={L.phone} hint="A UK mobile, for example 07911 123456" tid={tid("phone")} error={err("phone")} value={text("phone")} onChange={set("phone")} autoComplete="tel" short />
            </>
          )}

          {step === "guardian" && (
            <>
              <TextField id={id("guardian_name")} name="guardian_name" label={L.guardian_name} tid={tid("guardian_name")} error={err("guardian_name")} value={text("guardian_name")} onChange={set("guardian_name")} spellCheck={false} />
              <RadioGroup id={id("guardian_relationship")} name="guardian_relationship" label={L.guardian_relationship} tid={tid("guardian_relationship")} error={err("guardian_relationship")} options={RELATIONSHIPS} value={text("guardian_relationship")} onChange={set("guardian_relationship")} />
              <TextField id={id("guardian_phone")} name="guardian_phone" type="tel" label={L.guardian_phone} hint="Must be different from the student's number" tid={tid("guardian_phone")} error={err("guardian_phone")} value={text("guardian_phone")} onChange={set("guardian_phone")} short />
              <TextField id={id("guardian_email")} name="guardian_email" type="email" label={L.guardian_email} tid={tid("guardian_email")} error={err("guardian_email")} value={text("guardian_email")} onChange={set("guardian_email")} spellCheck={false} />
            </>
          )}

          {step === "course" && (
            <>
              <Combobox id={id("program")} name="program" label={L.program} hint="Start typing to search, for example data" tid={tid("program")} error={err("program")} options={PROGRAMMES} value={text("program")} onChange={set("program")} />
              <RadioGroup id={id("start_term")} name="start_term" label={L.start_term} tid={tid("start_term")} error={err("start_term")} options={TERMS} value={text("start_term")} onChange={set("start_term")} />
              <SelectField id={id("study_mode")} name="study_mode" label={L.study_mode} tid={tid("study_mode")} error={err("study_mode")} options={MODES} value={text("study_mode")} onChange={set("study_mode")} />
              <CheckField id={id("prior_enrollment")} name="prior_enrollment" label={L.prior_enrollment} tid={tid("prior_enrollment")} checked={values.prior_enrollment === true} onChange={set("prior_enrollment")} />
              {values.prior_enrollment === true && (
                <TextField id={id("prior_student_id")} name="prior_student_id" label={L.prior_student_id} hint="RA- followed by 6 digits, for example RA-204518" tid={tid("prior_student_id")} error={err("prior_student_id")} value={text("prior_student_id")} onChange={set("prior_student_id")} short spellCheck={false} />
              )}
            </>
          )}

          {step === "address" && (
            <>
              <TextField id={id("address_line1")} name="address_line1" label={L.address_line1} tid={tid("address_line1")} error={err("address_line1")} value={text("address_line1")} onChange={set("address_line1")} autoComplete="address-line1" />
              <TextField id={id("address_line2")} name="address_line2" label={L.address_line2} tid={tid("address_line2")} error={err("address_line2")} value={text("address_line2")} onChange={set("address_line2")} autoComplete="address-line2" />
              <TextField id={id("city")} name="city" label={L.city} tid={tid("city")} error={err("city")} value={text("city")} onChange={set("city")} autoComplete="address-level2" />
              <TextField id={id("postcode")} name="postcode" label={L.postcode} tid={tid("postcode")} error={err("postcode")} value={text("postcode")} onChange={set("postcode")} autoComplete="postal-code" short spellCheck={false} />
            </>
          )}

          {step === "review" && (
            <>
              <Review values={payload()} minor={minor === true} labels={L} onChange={(st) => { setErrors([]); setStep(st); }} variant={variant} />
              <CheckField id={id("consent_terms")} name="consent_terms" label={L.consent_terms} tid={tid("consent_terms")} error={err("consent_terms")} checked={values.consent_terms === true} onChange={set("consent_terms")} />
              <CheckField id={id("marketing_opt_in")} name="marketing_opt_in" label={L.marketing_opt_in} tid={tid("marketing_opt_in")} checked={values.marketing_opt_in === true} onChange={set("marketing_opt_in")} />
              {chaos === "captcha" && (
                <section className={s.captcha} aria-label="Security check" data-testid="captcha">
                  <p className={s.legend}>Security check</p>
                  <p className={s.hint}>We need to check that a person is sending this application.</p>
                  <label className={s.choice}><input type="checkbox" checked={human} onChange={(e) => setHuman(e.target.checked)} /> I am not a robot</label>
                </section>
              )}
            </>
          )}

          <div className={s.actions}>
            {step === "review" ? (
              <button type="submit" className={s.primary} disabled={sending || (chaos === "captcha" && !human)} aria-busy={sending} data-testid={btn("submit")}>
                {sending ? "Submitting…" : L.submit}
              </button>
            ) : (
              <button type="submit" className={s.primary} data-testid={btn("next")}>{L.next}</button>
            )}
            {position > 0 && <button type="button" className={s.secondary} onClick={back} data-testid={btn("back")}>{L.back}</button>}
          </div>
        </form>
      </main>
    </div>
  );
}

function Review({ values, minor, labels, onChange, variant }: { values: Values; minor: boolean; labels: Record<string, string>;
  onChange: (st: StepId) => void; variant: Variant }) {
  const v = (k: string) => (typeof values[k] === "string" ? (values[k] as string) : "");
  const rows: [StepId, string, string, string][] = [
    ["student", "first_name", labels.first_name, v("first_name")],
    ["student", "last_name", labels.last_name, v("last_name")],
    ["student", "date_of_birth", labels.date_of_birth, v("date_of_birth").split("-").reverse().join("/")],
    ["student", "email", labels.email, v("email")],
    ["student", "phone", labels.phone, v("phone")],
    ...(minor ? [
      ["guardian", "guardian_name", labels.guardian_name, v("guardian_name")],
      ["guardian", "guardian_relationship", labels.guardian_relationship, relationshipLabel(values.guardian_relationship)],
      ["guardian", "guardian_phone", labels.guardian_phone, v("guardian_phone")],
      ["guardian", "guardian_email", labels.guardian_email, v("guardian_email") || "Not given"],
    ] as [StepId, string, string, string][] : []),
    ["course", "program", labels.program, programmeLabel(values.program)],
    ["course", "start_term", labels.start_term, termLabel(values.start_term)],
    ["course", "study_mode", labels.study_mode, modeLabel(values.study_mode)],
    ["course", "prior_student_id", labels.prior_student_id, values.prior_enrollment === true ? v("prior_student_id") : "First time at Riverside"],
    ["address", "address", "Address", [v("address_line1"), v("address_line2"), v("city"), v("postcode").toUpperCase()].filter(Boolean).join(", ")],
  ];
  return (
    <dl className={s.review} data-testid={variant === "a" ? "ra-review" : undefined}>
      {rows.map(([st, key, label, value]) => (
        <div key={key} className={s.reviewRow}>
          <dt>{label}</dt>
          <dd data-testid={variant === "a" ? `ra-review-${key.replaceAll("_", "-")}` : undefined}>{value}</dd>
          <dd><button type="button" className={s.link} onClick={() => onChange(st)}>Change<span className="visually-hidden"> {label.toLowerCase()}</span></button></dd>
        </div>
      ))}
    </dl>
  );
}

function Confirmation({ done, onRestart, headingRef }: { done: Done; onRestart: () => void; headingRef: React.RefObject<HTMLHeadingElement | null> }) {
  const a = done.application;
  const rows: [string, string][] = [
    ["first_name", "First name"], ["last_name", "Last name"], ["date_of_birth", "Date of birth"], ["email", "Email"],
    ["phone", "Mobile"], ["guardian_name", "Guardian"], ["guardian_phone", "Guardian's mobile"], ["program", "Programme"],
    ["start_term", "Start term"], ["study_mode", "Study mode"], ["prior_student_id", "Previous student ID"],
    ["address_line1", "Address line 1"], ["address_line2", "Address line 2"], ["city", "Town or city"], ["postcode", "Postcode"],
  ];
  return (
    <div className={s.shell} style={{ gridTemplateColumns: "minmax(0, 1fr)", maxWidth: 760 }}>
      <main className={s.panel} data-testid="ra-confirmation">
        <div className={s.confirm}>
          <h1 className={s.title} style={{ color: "#fff" }} ref={headingRef} tabIndex={-1}>Application received</h1>
          <p>Your reference number</p>
          <p className={s.ref} data-testid="ra-confirmation-ref">{done.ref}</p>
        </div>
        <p>We have sent the application to our admissions team. They will contact you within five working days. Quote your reference if you get in touch.</p>
        <h2 className={s.reviewHeading}>What we received</h2>
        <dl className={s.review}>
          {rows.filter(([k]) => a[k] !== undefined && a[k] !== null && a[k] !== "").map(([k, label]) => (
            <div key={k} className={s.reviewRow} style={{ gridTemplateColumns: "minmax(9rem, 13rem) 1fr" }}>
              <dt>{label}</dt>
              <dd data-testid={`ra-confirm-${k.replaceAll("_", "-")}`} data-value={String(a[k])}>
                {k === "program" ? programmeLabel(a[k]) : k === "start_term" ? termLabel(a[k]) : k === "study_mode" ? modeLabel(a[k]) : String(a[k])}
              </dd>
            </div>
          ))}
        </dl>
        <button type="button" className={s.secondary} onClick={onRestart}>Start another application</button>
      </main>
    </div>
  );
}
