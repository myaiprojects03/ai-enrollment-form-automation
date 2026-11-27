"use client";
/** Riverside's form controls. The programme picker and the date picker are deliberately custom widgets
 * (an ARIA combobox and a calendar popover), the kind real portals use and automation must handle. */
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { isoToUk, ukToIso } from "@/lib/portals/common";
import s from "../riverside.module.css";

type Opt = { value: string; label: string };
type Common = { id: string; name: string; label: string; hint?: string; error?: string; tid?: string };

function describedBy(id: string, hint?: string, error?: string): string | undefined {
  const ids = [hint ? `${id}-hint` : "", error ? `${id}-error` : ""].filter(Boolean).join(" ");
  return ids || undefined;
}

function Wrap({ id, hint, error, tid, label, children, as = "div" }: Common & { children: React.ReactNode; as?: "div" | "fieldset" }) {
  const cls = `${s.field} ${error ? s.fieldInvalid : ""}`;
  const head = (
    <>
      {as === "fieldset" ? <legend className={s.legend}>{label}</legend> : <label className={s.label} htmlFor={id}>{label}</label>}
      {hint && <p className={s.hint} id={`${id}-hint`}>{hint}</p>}
      {error && <p className={s.error} id={`${id}-error`} data-testid={tid ? `${tid}-error` : undefined}><span className="visually-hidden">Error: </span>{error}</p>}
    </>
  );
  return as === "fieldset"
    ? <fieldset className={cls} data-testid={tid} aria-describedby={describedBy(id, hint, error)}>{head}{children}</fieldset>
    : <div className={cls}>{head}{children}</div>;
}

export function TextField(p: Common & { value: string; onChange: (v: string) => void; type?: string; autoComplete?: string;
  short?: boolean; inputMode?: React.HTMLAttributes<HTMLInputElement>["inputMode"]; spellCheck?: boolean }) {
  return (
    <Wrap {...p}>
      <input id={p.id} name={p.name} type={p.type ?? "text"} className={`${s.input} ${p.short ? s.inputShort : ""}`}
        value={p.value} onChange={(e) => p.onChange(e.target.value)} autoComplete={p.autoComplete} inputMode={p.inputMode}
        spellCheck={p.spellCheck} aria-invalid={p.error ? true : undefined} aria-describedby={describedBy(p.id, p.hint, p.error)}
        data-testid={p.tid} />
    </Wrap>
  );
}

export function SelectField(p: Common & { value: string; onChange: (v: string) => void; options: readonly Opt[] }) {
  return (
    <Wrap {...p}>
      <select id={p.id} name={p.name} className={`${s.input} ${s.inputShort}`} value={p.value} onChange={(e) => p.onChange(e.target.value)}
        aria-invalid={p.error ? true : undefined} aria-describedby={describedBy(p.id, p.hint, p.error)} data-testid={p.tid}>
        <option value="">Select</option>
        {p.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </Wrap>
  );
}

export function RadioGroup(p: Common & { value: string; onChange: (v: string) => void; options: readonly Opt[] }) {
  return (
    <Wrap {...p} as="fieldset">
      <div className={s.choices}>
        {p.options.map((o) => (
          <label key={o.value} className={s.choice}>
            <input type="radio" name={p.name} value={o.value} checked={p.value === o.value} onChange={() => p.onChange(o.value)}
              id={`${p.id}-${o.value}`} data-testid={p.tid ? `${p.tid}-${o.value}` : undefined} />
            {o.label}
          </label>
        ))}
      </div>
    </Wrap>
  );
}

export function CheckField(p: Omit<Common, "label"> & { label: React.ReactNode; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className={`${s.field} ${p.error ? s.fieldInvalid : ""}`}>
      {p.error && <p className={s.error} id={`${p.id}-error`} data-testid={p.tid ? `${p.tid}-error` : undefined}><span className="visually-hidden">Error: </span>{p.error}</p>}
      <label className={s.choice}>
        <input type="checkbox" id={p.id} name={p.name} checked={p.checked} onChange={(e) => p.onChange(e.target.checked)}
          aria-invalid={p.error ? true : undefined} aria-describedby={p.error ? `${p.id}-error` : undefined} data-testid={p.tid} />
        <span>{p.label}</span>
      </label>
    </div>
  );
}

/** Type to filter, arrows to move, Enter or click to choose. Only a choice from the list counts. */
export function Combobox(p: Common & { value: string; onChange: (v: string) => void; options: readonly Opt[] }) {
  const selected = p.options.find((o) => o.value === p.value);
  const [text, setText] = useState(selected?.label ?? "");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listId = `${p.id}-listbox`;

  useEffect(() => { if (selected) setText(selected.label); }, [selected]);

  const shown = useMemo(() => {
    const q = text.trim().toLowerCase();
    if (!q || (selected && selected.label === text)) return p.options;
    // Match the start of any word ("sec" finds Cyber Security), not any fragment ("dat" is not in Foundation).
    return p.options.filter((o) => o.label.toLowerCase().split(/[\s()]+/).some((w) => w.startsWith(q)) || o.label.toLowerCase().startsWith(q));
  }, [text, selected, p.options]);

  const choose = (o: Opt) => { p.onChange(o.value); setText(o.label); setOpen(false); };
  const exact = (t: string) => p.options.find((o) => o.label.toLowerCase() === t.trim().toLowerCase());

  return (
    <Wrap {...p}>
      <div className={s.combo}>
        <input id={p.id} name={p.name} className={s.input} role="combobox" aria-autocomplete="list" aria-expanded={open}
          aria-controls={listId} autoComplete="off" value={text} data-testid={p.tid}
          aria-activedescendant={open && shown[active] ? `${p.id}-opt-${shown[active].value}` : undefined}
          aria-invalid={p.error ? true : undefined} aria-describedby={describedBy(p.id, p.hint, p.error)}
          onChange={(e) => { setText(e.target.value); setOpen(true); setActive(0); p.onChange(exact(e.target.value)?.value ?? ""); }}
          onFocus={() => setOpen(true)}
          onClick={() => setOpen(true)}
          onBlur={() => { setOpen(false); const m = exact(text); if (m) choose(m); }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, shown.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
            else if (e.key === "Enter" && open && shown[active]) { e.preventDefault(); choose(shown[active]); }
            else if (e.key === "Escape") setOpen(false);
          }} />
        {open && (
          <ul className={s.listbox} id={listId} role="listbox" aria-label={p.label} data-testid={p.tid ? `${p.tid}-listbox` : undefined}>
            {shown.length === 0 && <li className={s.noMatch} role="presentation">No programme matches “{text}”</li>}
            {shown.map((o, i) => (
              <li key={o.value} id={`${p.id}-opt-${o.value}`} role="option" aria-selected={o.value === p.value}
                className={`${s.option} ${i === active ? s.optionActive : ""}`} data-testid={p.tid ? `${p.tid}-option-${o.value}` : undefined}
                onMouseDown={(e) => { e.preventDefault(); choose(o); }} onMouseEnter={() => setActive(i)}>
                {o.label}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Wrap>
  );
}

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** DD/MM/YYYY typed, or picked from a calendar. `value` is the text as typed. */
export function DateField(p: Common & { value: string; onChange: (v: string) => void; earliest: number; latest: number; startYear: number }) {
  const [open, setOpen] = useState(false);
  const iso = ukToIso(p.value);
  const [year, setYear] = useState(iso ? +iso.slice(0, 4) : p.startYear);
  const [month, setMonth] = useState(iso ? +iso.slice(5, 7) - 1 : 0);
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const calId = useId();

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const first = new Date(Date.UTC(year, month, 1)).getUTCDay();
  const lead = (first + 6) % 7; // weeks start on Monday
  const days = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const years = Array.from({ length: p.latest - p.earliest + 1 }, (_, i) => p.latest - i);
  const pick = (d: number) => {
    p.onChange(isoToUk(`${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`));
    setOpen(false);
    input.current?.focus();
  };

  return (
    <Wrap {...p}>
      <div className={s.dateWrap} ref={box} onKeyDown={(e) => { if (e.key === "Escape" && open) { setOpen(false); input.current?.focus(); } }}>
        <div className={s.dateRow}>
          <input ref={input} id={p.id} name={p.name} className={`${s.input} ${s.inputShort}`} inputMode="numeric" placeholder="DD/MM/YYYY"
            autoComplete="bday" value={p.value} onChange={(e) => p.onChange(e.target.value)} data-testid={p.tid}
            aria-invalid={p.error ? true : undefined} aria-describedby={describedBy(p.id, p.hint, p.error)} />
          <button type="button" className={s.iconButton} aria-label="Choose date from calendar" aria-expanded={open} aria-controls={calId}
            data-testid={p.tid ? `${p.tid}-calendar-button` : undefined} onClick={() => setOpen((o) => !o)}>
            <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><rect x="2" y="4" width="16" height="14" rx="2" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M2 8h16M6 2v4M14 2v4" stroke="currentColor" strokeWidth="2" /></svg>
          </button>
        </div>
        {open && (
          <div className={s.calendar} id={calId} role="dialog" aria-label="Choose a date" data-testid={p.tid ? `${p.tid}-calendar` : undefined}>
            <div className={s.calHead}>
              <select aria-label="Month" value={month} onChange={(e) => setMonth(+e.target.value)}>
                {MONTHS.map((m, i) => <option key={m} value={i}>{m}</option>)}
              </select>
              <select aria-label="Year" value={year} onChange={(e) => setYear(+e.target.value)}>
                {years.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
            </div>
            <div className={s.calGrid}>
              {["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((d) => <span key={d} className={s.dow} aria-hidden="true">{d}</span>)}
              {Array.from({ length: lead }, (_, i) => <span key={`x${i}`} />)}
              {Array.from({ length: days }, (_, i) => (
                <button key={i} type="button" className={s.day} onClick={() => pick(i + 1)}
                  aria-label={`${i + 1} ${MONTHS[month]} ${year}`}>{i + 1}</button>
              ))}
            </div>
          </div>
        )}
      </div>
    </Wrap>
  );
}
