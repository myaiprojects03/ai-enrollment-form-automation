/** Rules both mock portals share. The portals are stand-ins for third-party sites: they validate on their own
 * terms (and their messages are theirs), independently of the engine's validator. */

export type FieldError = { field: string; message: string };
export type Values = Record<string, unknown>;

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const POSTCODE = /^([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})$/i;
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

export const str = (v: unknown): string => (typeof v === "string" ? v.trim() : "");

export function isEmail(v: string): boolean {
  return v.length <= 254 && EMAIL.test(v);
}

/** UK numbers as typed by people: spaces, dashes, brackets, a leading 0 or +44. Returns +44... or null. */
export function ukPhone(v: string): string | null {
  const s = v.replace(/[\s\-().]/g, "");
  const m = /^(?:\+44|0044|0)(\d{9,10})$/.exec(s);
  return m ? `+44${m[1]}` : null;
}

export function ukPostcode(v: string): string | null {
  const m = POSTCODE.exec(v.trim());
  return m ? `${m[1]} ${m[2]}`.toUpperCase() : null;
}

/** A real calendar date in YYYY-MM-DD, as a UTC Date; null for 2026-02-30 and friends. */
export function isoDate(v: string): Date | null {
  const m = ISO_DATE.exec(v.trim());
  if (!m) return null;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3] ? d : null;
}

/** DD/MM/YYYY (how people in the UK write dates) to YYYY-MM-DD; "" when it is not a real date. */
export function ukToIso(v: string): string {
  const m = /^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})$/.exec(v.trim());
  if (!m) return "";
  const iso = `${m[3]}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}`;
  return isoDate(iso) ? iso : "";
}

export function isoToUk(v: string): string {
  const m = ISO_DATE.exec(v);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : "";
}

export function todayUtc(): Date {
  const n = new Date();
  return new Date(Date.UTC(n.getUTCFullYear(), n.getUTCMonth(), n.getUTCDate()));
}

export function ageOn(dob: Date, on: Date): number {
  let age = on.getUTCFullYear() - dob.getUTCFullYear();
  const before = on.getUTCMonth() < dob.getUTCMonth() ||
    (on.getUTCMonth() === dob.getUTCMonth() && on.getUTCDate() < dob.getUTCDate());
  if (before) age -= 1;
  return age;
}

export const NAME = /^[\p{L}][\p{L}\p{M}' .-]{0,79}$/u;

export function requireName(errors: FieldError[], field: string, v: unknown, label: string): void {
  const s = str(v);
  if (!s) errors.push({ field, message: `Enter ${label}.` });
  else if (!NAME.test(s)) errors.push({ field, message: `${label[0].toUpperCase()}${label.slice(1)} can only contain letters, spaces, hyphens and apostrophes.` });
}

export function forFields(errors: FieldError[], fields: readonly string[]): FieldError[] {
  return errors.filter((e) => fields.includes(e.field));
}
