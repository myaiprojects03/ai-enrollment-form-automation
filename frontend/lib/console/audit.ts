/** Plain-English audit entries. Details never hold personal values, only field names, codes and references. */
export const ACTIONS: Record<string, string> = {
  "enrollment.received": "Received", "mapping.completed": "Mapped", "validation.outcome": "Checked", "fields.edited": "Edited fields",
  "personal_data.viewed": "Opened personal data", "enrollment.approved": "Approved", "enrollment.rejected": "Rejected",
  "submission.succeeded": "Submitted", "submission.failed": "Submission failed", "locator.healed": "Found changed page elements",
  "screenshot.viewed": "Viewed a screenshot", "duplicate.suspected": "Possible duplicate", "staff.login": "Signed in", "staff.login_failed": "Failed sign-in",
};

export function describeDetails(d: Record<string, unknown>): string {
  if (Array.isArray(d.fields)) return (d.fields as string[]).join(", ");
  if (typeof d.outcome === "string") return `${d.outcome.replace("_", " ").toLowerCase()}${Array.isArray(d.codes) && d.codes.length ? `: ${(d.codes as string[]).join(", ").toLowerCase().replaceAll("_", " ")}` : ""}`;
  if (typeof d.confirmation_ref === "string") return `${d.confirmation_ref} by ${d.path}${d.adopted ? " (already at the portal)" : ""}, read-back ${d.readback}`;
  if (typeof d.code === "string") return `${String(d.code).toLowerCase().replaceAll("_", " ")} after ${d.attempts ?? 1} attempt(s)`;
  if (Array.isArray(d.healed)) return `${d.healed.length} element(s)`;
  if (typeof d.mapper === "string") return `${d.mapper}, ${d.mapped} fields${d.llm_error ? `, AI: ${d.llm_error}` : ""}`;
  if (typeof d.note === "string" && d.note) return d.note;
  return "";
}

