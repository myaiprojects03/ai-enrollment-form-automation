/** The console's calls to the engine, through the server-side proxy. */
export type Severity = "block" | "review" | "info";
export type Reason = { code: string; field: string | null; message: string; severity: Severity; accepted_by?: string };
export type Summary = {
  enrollment_id: string; target_form: string; source: string; status: string; outcome: string | null;
  reasons: Reason[]; submit_path: string | null; confirmation_ref: string | null; mapper: string | null;
  min_confidence: number | null; created_at: string; updated_at: string;
};
export type Field = {
  field: string; label: string; required: boolean; state: string; confidence: number; method: string;
  source_fields: string[]; candidates: string[]; has_assumption: boolean; value?: unknown; assumption?: string | null;
};
export type AuditEntry = { actor: string; action: string; details: Record<string, unknown>; at: string; enrollment_id?: string | null };
export type Detail = Summary & {
  fields: Field[]; audit: AuditEntry[]; source_record?: Record<string, unknown>; mapped_payload?: Record<string, unknown>;
  mapping: { llm_used?: boolean; llm_error?: string | null; unused_source_fields?: string[] };
};
export type Run = {
  run_id: string; attempt: number; path: string; status: string; error_code: string | null; error_detail: string | null;
  confirmation_ref: string | null; steps: Record<string, unknown>[]; options: Record<string, string>;
  actor: string; started_at: string; finished_at: string | null; duration_ms: number | null;
  screenshots: { id: number; seq: number; label: string; bytes: number }[];
};
export type Option = { value: string; label: string };
export type FormField = { name: string; label: string; type: string; required: boolean; options: Option[]; hint: string;
  when: { field: string; values: unknown[] } | null };
export type Form = { id: string; name: string; portal: string; signoff_required: boolean; fields: FormField[] };

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function message(data: unknown, status: number): string {
  const d = (data as { detail?: unknown })?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => (x as { msg?: string }).msg ?? "").filter(Boolean).join("; ") || `Error ${status}`;
  return status === 502 ? "The engine is not reachable." : `Something went wrong (${status}).`;
}

export async function api<T>(path: string, init: { method?: string; json?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;
  if (init.json !== undefined) { headers["content-type"] = "application/json"; body = JSON.stringify(init.json); }
  if (init.form) body = init.form;
  if ((init.method ?? "GET") !== "GET") headers["x-console"] = "1";
  const res = await fetch(`/api/console/engine/${path}`, { method: init.method ?? "GET", headers, body, cache: "no-store" });
  if (res.status === 401 && typeof window !== "undefined") {
    window.location.href = `/console/login?next=${encodeURIComponent(window.location.pathname)}`;
    throw new ApiError(401, "Sign in again.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, message(data, res.status));
  return data as T;
}

export const STATUS_LABEL: Record<string, string> = {
  needs_review: "Needs review", blocked: "Blocked", failed: "Failed", approved: "Ready to submit",
  submitting: "Submitting", submitted: "Submitted", rejected: "Rejected", received: "Received", mapped: "Mapped",
};

export function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}
