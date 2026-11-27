/** Harbour Sports Club's membership form: options and validation (used by the page and both of its APIs). */
import { ageOn, type FieldError, isEmail, isoDate, requireName, str, ukPhone, type Values } from "./common";

export const MEMBERSHIPS = [
  { value: "adult", label: "Adult", note: "Full access, any time" },
  { value: "student", label: "Student", note: "Needs a valid student card" },
  { value: "family", label: "Family", note: "Two to six people at one address" },
  { value: "off_peak", label: "Off-peak", note: "Weekdays before 4pm" },
] as const;

export const INTERESTS = [
  { value: "swimming", label: "Swimming" },
  { value: "tennis", label: "Tennis" },
  { value: "gym", label: "Gym" },
  { value: "yoga", label: "Yoga" },
  { value: "squash", label: "Squash" },
  { value: "climbing", label: "Climbing" },
] as const;

export const REFERRALS = [
  { value: "friend", label: "A friend" },
  { value: "social", label: "Social media" },
  { value: "search", label: "Search engine" },
  { value: "event", label: "Local event" },
  { value: "other", label: "Other" },
] as const;

export const FIELDS = ["full_name", "email", "phone", "date_of_birth", "membership_type", "student_id",
  "family_members", "start_date", "interests", "emergency_contact_name", "emergency_contact_phone", "how_heard",
  "accept_terms"] as const;

export const MAX_START_DAYS = 90;
const has = <T extends { value: string }>(list: readonly T[], v: unknown) => list.some((o) => o.value === v);

function familySize(v: unknown): number | null {
  if (typeof v === "number" && Number.isInteger(v)) return v;
  if (typeof v === "string" && /^\d+$/.test(v.trim())) return Number(v.trim());
  return null;
}

export function validateHarbour(v: Values, today: Date): FieldError[] {
  const e: FieldError[] = [];
  for (const k of Object.keys(v)) {
    if (!(FIELDS as readonly string[]).includes(k)) e.push({ field: k, message: "Unknown field." });
  }
  requireName(e, "full_name", v.full_name, "your full name");
  if (!str(v.email)) e.push({ field: "email", message: "Enter your email." });
  else if (!isEmail(str(v.email))) e.push({ field: "email", message: "That email doesn't look right." });
  const phone = ukPhone(str(v.phone));
  if (!str(v.phone)) e.push({ field: "phone", message: "Enter your phone number." });
  else if (!phone) e.push({ field: "phone", message: "Use a UK number, like 07911 123456." });

  const dob = isoDate(str(v.date_of_birth));
  if (!str(v.date_of_birth)) e.push({ field: "date_of_birth", message: "Enter your date of birth." });
  else if (!dob) e.push({ field: "date_of_birth", message: "Enter a real date." });
  else if (ageOn(dob, today) < 16) e.push({ field: "date_of_birth", message: "Members must be 16 or older." });
  else if (ageOn(dob, today) > 110) e.push({ field: "date_of_birth", message: "Check the year of birth." });

  const type = v.membership_type;
  if (!has(MEMBERSHIPS, type)) e.push({ field: "membership_type", message: "Pick a membership." });
  const sid = str(v.student_id).replace(/[\s-]/g, "");
  if (type === "student") {
    if (!sid) e.push({ field: "student_id", message: "Enter your student card number." });
    else if (!/^[A-Z0-9]{6,12}$/i.test(sid)) e.push({ field: "student_id", message: "Student card numbers are 6 to 12 letters or digits." });
  } else if (sid) e.push({ field: "student_id", message: "Only needed for a student membership." });
  const fam = v.family_members;
  const famGiven = fam !== undefined && fam !== null && fam !== "";
  if (type === "family") {
    const n = familySize(fam);
    if (!famGiven) e.push({ field: "family_members", message: "Say how many people are on the membership." });
    else if (n === null || n < 2 || n > 6) e.push({ field: "family_members", message: "A family membership covers 2 to 6 people." });
  } else if (famGiven) e.push({ field: "family_members", message: "Only needed for a family membership." });

  const start = isoDate(str(v.start_date));
  if (!str(v.start_date)) e.push({ field: "start_date", message: "Choose a start date." });
  else if (!start) e.push({ field: "start_date", message: "Enter a real date." });
  else {
    const days = Math.round((start.getTime() - today.getTime()) / 86_400_000);
    if (days < 0) e.push({ field: "start_date", message: "The start date can't be in the past." });
    else if (days > MAX_START_DAYS) e.push({ field: "start_date", message: `Start within ${MAX_START_DAYS} days of today.` });
  }

  const interests = Array.isArray(v.interests) ? v.interests : [];
  if (interests.length === 0) e.push({ field: "interests", message: "Pick at least one interest." });
  else if (!interests.every((i) => has(INTERESTS, i))) e.push({ field: "interests", message: "Pick interests from the list." });

  requireName(e, "emergency_contact_name", v.emergency_contact_name, "an emergency contact");
  const ep = ukPhone(str(v.emergency_contact_phone));
  if (!str(v.emergency_contact_phone)) e.push({ field: "emergency_contact_phone", message: "Enter your emergency contact's phone." });
  else if (!ep) e.push({ field: "emergency_contact_phone", message: "Use a UK number for your emergency contact." });
  else if (ep === phone) e.push({ field: "emergency_contact_phone", message: "Your emergency contact needs a different number from yours." });

  if (str(v.how_heard) && !has(REFERRALS, v.how_heard)) e.push({ field: "how_heard", message: "Pick an option from the list." });
  if (v.accept_terms !== true) e.push({ field: "accept_terms", message: "Accept the membership terms to join." });
  return e;
}

export function normaliseHarbour(v: Values): Values {
  const type = str(v.membership_type);
  return {
    full_name: str(v.full_name),
    email: str(v.email).toLowerCase(),
    phone: ukPhone(str(v.phone)),
    date_of_birth: str(v.date_of_birth),
    membership_type: type,
    student_id: type === "student" ? str(v.student_id).replace(/[\s-]/g, "").toUpperCase() : null,
    family_members: type === "family" ? familySize(v.family_members) : null,
    start_date: str(v.start_date),
    interests: [...new Set(v.interests as string[])],
    emergency_contact_name: str(v.emergency_contact_name),
    emergency_contact_phone: ukPhone(str(v.emergency_contact_phone)),
    how_heard: str(v.how_heard) || null,
    accept_terms: true,
  };
}
