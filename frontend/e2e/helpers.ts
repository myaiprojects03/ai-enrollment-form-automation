import { randomUUID } from "node:crypto";

export const KEY = { "x-portal-key": "e2e-portal-key" };
export const email = (who: string) => `${who}.${randomUUID().slice(0, 8)}@example.com`;

const pad = (n: number) => String(n).padStart(2, "0");
const now = new Date();
/** A date of birth for someone who turns `age` this year, a little after New Year (stable whatever today is). */
export const dobUk = (age: number) => `03/02/${now.getUTCFullYear() - age - 1}`;
export const dobIso = (age: number) => `${now.getUTCFullYear() - age - 1}-02-03`;
export const inDays = (n: number) => {
  const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + n));
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
};

export function member(over: Record<string, unknown> = {}) {
  return {
    full_name: "Sofia Marin", email: email("sofia"), phone: "07800 345678", date_of_birth: dobIso(34),
    membership_type: "adult", start_date: inDays(7), interests: ["swimming", "yoga"],
    emergency_contact_name: "Dan Marin", emergency_contact_phone: "07900 456789", accept_terms: true, ...over,
  };
}

export function application(over: Record<string, unknown> = {}) {
  return {
    first_name: "Amara", last_name: "Okafor", date_of_birth: dobIso(28), email: email("amara"), phone: "07911 123456",
    program: "data-analytics", start_term: "2027-01", study_mode: "part_time", address_line1: "14 Mill Lane", city: "Leeds",
    postcode: "ls1 4ap", consent_terms: true, ...over,
  };
}
