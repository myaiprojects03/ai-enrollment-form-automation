/** Riverside Academy's course application: options, steps and validation (used by the page and its API). */
import { ageOn, type FieldError, isEmail, isoDate, requireName, str, ukPhone, ukPostcode, type Values } from "./common";

export const PROGRAMMES = [
  { value: "cs-foundation", label: "Computer Science Foundation" },
  { value: "data-analytics", label: "Data Analytics (Level 4)" },
  { value: "cyber-security", label: "Cyber Security Essentials" },
  { value: "business-admin", label: "Business Administration" },
  { value: "graphic-design", label: "Graphic Design" },
  { value: "accounting", label: "Accounting (AAT Level 3)" },
  { value: "web-development", label: "Web Development Bootcamp" },
  { value: "project-management", label: "Project Management (PRINCE2)" },
] as const;

export const TERMS = [
  { value: "2027-01", label: "January 2027" },
  { value: "2027-04", label: "April 2027" },
  { value: "2027-09", label: "September 2027" },
] as const;

export const MODES = [
  { value: "full_time", label: "Full-time" },
  { value: "part_time", label: "Part-time" },
  { value: "online", label: "Online" },
] as const;

export const RELATIONSHIPS = [
  { value: "parent", label: "Parent" },
  { value: "guardian", label: "Legal guardian" },
  { value: "other", label: "Other" },
] as const;

export type StepId = "student" | "guardian" | "course" | "address" | "review";

export const STEP_FIELDS: Record<StepId, readonly string[]> = {
  student: ["first_name", "last_name", "date_of_birth", "email", "phone"],
  guardian: ["guardian_name", "guardian_relationship", "guardian_phone", "guardian_email"],
  course: ["program", "start_term", "study_mode", "prior_enrollment", "prior_student_id"],
  address: ["address_line1", "address_line2", "city", "postcode"],
  review: ["consent_terms", "marketing_opt_in"],
};

export const ALL_FIELDS = Object.values(STEP_FIELDS).flat();

const has = <T extends { value: string }>(list: readonly T[], v: unknown) => list.some((o) => o.value === v);

export function isMinor(dobIso: unknown, today: Date): boolean | null {
  const d = isoDate(str(dobIso));
  return d ? ageOn(d, today) < 18 : null;
}

/** Every problem with an application. `date_of_birth` is YYYY-MM-DD here; the page converts what was typed. */
export function validateRiverside(v: Values, today: Date): FieldError[] {
  const e: FieldError[] = [];
  const unknown = Object.keys(v).filter((k) => !ALL_FIELDS.includes(k));
  for (const k of unknown) e.push({ field: k, message: "This field is not part of the application." });

  requireName(e, "first_name", v.first_name, "your first name");
  requireName(e, "last_name", v.last_name, "your last name");
  const dob = isoDate(str(v.date_of_birth));
  if (!str(v.date_of_birth)) e.push({ field: "date_of_birth", message: "Enter your date of birth." });
  else if (!dob) e.push({ field: "date_of_birth", message: "Date of birth must be a real date, like 27/03/2007." });
  else if (ageOn(dob, today) < 14 || ageOn(dob, today) > 99) e.push({ field: "date_of_birth", message: "Students must be aged 14 to 99." });
  if (!str(v.email)) e.push({ field: "email", message: "Enter your email address." });
  else if (!isEmail(str(v.email))) e.push({ field: "email", message: "Enter an email address like name@example.com." });
  const phone = ukPhone(str(v.phone));
  if (!str(v.phone)) e.push({ field: "phone", message: "Enter your mobile number." });
  else if (!phone) e.push({ field: "phone", message: "Enter a UK mobile number, like 07911 123456." });

  const minor = dob ? ageOn(dob, today) < 18 : false;
  const guardianGiven = ["guardian_name", "guardian_relationship", "guardian_phone", "guardian_email"].some((k) => str(v[k]));
  if (minor) {
    requireName(e, "guardian_name", v.guardian_name, "the guardian's full name");
    if (!has(RELATIONSHIPS, v.guardian_relationship)) e.push({ field: "guardian_relationship", message: "Select how the guardian is related to the student." });
    const gp = ukPhone(str(v.guardian_phone));
    if (!str(v.guardian_phone)) e.push({ field: "guardian_phone", message: "Enter the guardian's mobile number." });
    else if (!gp) e.push({ field: "guardian_phone", message: "Enter a UK mobile number for the guardian." });
    else if (gp === phone) e.push({ field: "guardian_phone", message: "The guardian's number must be different from the student's." });
    if (str(v.guardian_email) && !isEmail(str(v.guardian_email))) e.push({ field: "guardian_email", message: "Enter the guardian's email like name@example.com." });
  } else if (dob && guardianGiven) {
    e.push({ field: "guardian_name", message: "Guardian details are only needed for students under 18." });
  }

  if (!str(v.program)) e.push({ field: "program", message: "Choose a programme." });
  else if (!has(PROGRAMMES, v.program)) e.push({ field: "program", message: "Choose a programme from the list." });
  if (!has(TERMS, v.start_term)) e.push({ field: "start_term", message: "Select a start term." });
  if (!has(MODES, v.study_mode)) e.push({ field: "study_mode", message: "Select a study mode." });
  if (v.prior_enrollment === true) {
    if (!str(v.prior_student_id)) e.push({ field: "prior_student_id", message: "Enter your previous student ID." });
    else if (!/^RA-\d{6}$/i.test(str(v.prior_student_id))) e.push({ field: "prior_student_id", message: "Student ID must look like RA-123456." });
  } else if (str(v.prior_student_id)) {
    e.push({ field: "prior_student_id", message: "Only enter a student ID if you have studied here before." });
  }

  if (!str(v.address_line1)) e.push({ field: "address_line1", message: "Enter the first line of your address." });
  if (!str(v.city)) e.push({ field: "city", message: "Enter your town or city." });
  if (!str(v.postcode)) e.push({ field: "postcode", message: "Enter your postcode." });
  else if (!ukPostcode(str(v.postcode))) e.push({ field: "postcode", message: "Enter a real UK postcode, like LS1 4AP." });
  for (const k of ["address_line1", "address_line2", "city"]) {
    if (str(v[k]).length > 100) e.push({ field: k, message: "Keep this to 100 characters or fewer." });
  }

  if (v.consent_terms !== true) e.push({ field: "consent_terms", message: "You must agree to the enrollment terms." });
  return e;
}

/** What the academy stores: trimmed, phones and postcode in one format. Call only on a valid application. */
export function normaliseRiverside(v: Values): Values {
  const out: Values = {};
  for (const k of ALL_FIELDS) {
    const val = v[k];
    if (typeof val === "boolean") out[k] = val;
    else if (str(val)) out[k] = str(val);
  }
  out.email = str(v.email).toLowerCase();
  out.phone = ukPhone(str(v.phone));
  if (out.guardian_phone) out.guardian_phone = ukPhone(str(v.guardian_phone));
  if (out.prior_student_id) out.prior_student_id = str(v.prior_student_id).toUpperCase();
  out.postcode = ukPostcode(str(v.postcode));
  out.prior_enrollment = v.prior_enrollment === true;
  out.marketing_opt_in = v.marketing_opt_in === true;
  return out;
}

export const programmeLabel = (v: unknown) => PROGRAMMES.find((p) => p.value === v)?.label ?? "";
export const termLabel = (v: unknown) => TERMS.find((p) => p.value === v)?.label ?? "";
export const modeLabel = (v: unknown) => MODES.find((p) => p.value === v)?.label ?? "";
export const relationshipLabel = (v: unknown) => RELATIONSHIPS.find((p) => p.value === v)?.label ?? "";
