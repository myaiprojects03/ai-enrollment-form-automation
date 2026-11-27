/** Server-side pieces of the mock portals: storage, the API key, and simulated failures.
 * Storage is Postgres when PORTAL_DATABASE_URL is set (the deployed demo) and memory otherwise (local runs, tests). */
import "server-only";
import { randomInt, timingSafeEqual } from "node:crypto";
import { Pool } from "pg";

export type Stored = { ref: string; portal: "riverside" | "harbour"; email: string; data: Record<string, unknown>; created_at: string };

type Mem = { rows: Stored[]; attempts: Map<string, number> };
const g = globalThis as unknown as { __portalMem?: Mem; __portalPool?: Pool; __portalReady?: Promise<void> };
const mem: Mem = (g.__portalMem ??= { rows: [], attempts: new Map() });

function pool(): Pool | null {
  const url = process.env.PORTAL_DATABASE_URL;
  if (!url) return null;
  if (!g.__portalPool) {
    g.__portalPool = new Pool({ connectionString: url, max: 3, ssl: /sslmode=require|neon\.tech/.test(url) ? { rejectUnauthorized: false } : undefined });
    g.__portalReady = g.__portalPool.query(`CREATE TABLE IF NOT EXISTS portal_submissions (
        ref TEXT PRIMARY KEY, portal TEXT NOT NULL, email TEXT NOT NULL, data JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now());
      CREATE INDEX IF NOT EXISTS portal_submissions_email ON portal_submissions (portal, email);`).then(() => undefined);
  }
  return g.__portalPool;
}

async function db(): Promise<Pool | null> {
  const p = pool();
  if (p) await g.__portalReady;
  return p;
}

const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
export function newRef(portal: Stored["portal"]): string {
  if (portal === "harbour") return `HSC-${randomInt(100000, 999999)}`;
  return `RVA-${new Date().getUTCFullYear()}-${Array.from({ length: 5 }, () => ALPHABET[randomInt(ALPHABET.length)]).join("")}`;
}

export async function save(portal: Stored["portal"], email: string, data: Record<string, unknown>): Promise<Stored> {
  const row: Stored = { ref: newRef(portal), portal, email, data, created_at: new Date().toISOString() };
  const p = await db();
  if (p) await p.query("INSERT INTO portal_submissions (ref, portal, email, data) VALUES ($1, $2, $3, $4)", [row.ref, portal, email, row.data]);
  else mem.rows.push(row);
  return row;
}

export async function byRef(portal: Stored["portal"], ref: string): Promise<Stored | null> {
  const p = await db();
  if (!p) return mem.rows.find((r) => r.portal === portal && r.ref === ref) ?? null;
  const { rows } = await p.query("SELECT ref, portal, email, data, created_at FROM portal_submissions WHERE portal = $1 AND ref = $2", [portal, ref]);
  return rows[0] ? { ...rows[0], created_at: new Date(rows[0].created_at).toISOString() } : null;
}

export async function byEmail(portal: Stored["portal"], email: string): Promise<Stored[]> {
  const p = await db();
  const e = email.trim().toLowerCase();
  if (!p) return mem.rows.filter((r) => r.portal === portal && r.email === e);
  const { rows } = await p.query("SELECT ref, portal, email, data, created_at FROM portal_submissions WHERE portal = $1 AND email = $2 ORDER BY created_at", [portal, e]);
  return rows.map((r) => ({ ...r, created_at: new Date(r.created_at).toISOString() }));
}

/** The key that machine callers (the engine's API path and read-back) send as X-Portal-Key. */
export function keyOk(req: Request): boolean {
  const expected = process.env.PORTAL_API_KEY || (process.env.NODE_ENV === "production" ? "" : "dev-portal-key");
  const given = req.headers.get("x-portal-key") ?? "";
  if (!expected || given.length !== expected.length) return false;
  return timingSafeEqual(Buffer.from(given), Buffer.from(expected));
}

export const json = (body: unknown, status = 200) => Response.json(body, { status, headers: { "cache-control": "no-store" } });

/** Simulated trouble, so the engine's retries, read-back and halts can be shown working.
 *  slow:  answers after 3 s          flaky: every first attempt for an email fails with 503
 *  down:  always 503                 lost:  saves, then answers 504 as if the reply never arrived */
export type Chaos = "slow" | "flaky" | "down" | "lost" | "";

export function chaosOf(req: Request): Chaos {
  const raw = req.headers.get("x-portal-chaos") ?? new URL(req.url).searchParams.get("chaos") ?? "";
  return (["slow", "flaky", "down", "lost"] as const).find((c) => c === raw) ?? "";
}

export async function beforeSave(chaos: Chaos, email: string): Promise<Response | null> {
  if (chaos === "slow") await new Promise((r) => setTimeout(r, 3000));
  if (chaos === "down") return json({ error: "The service is temporarily unavailable. Please try again later." }, 503);
  if (chaos === "flaky") {
    const n = (mem.attempts.get(email) ?? 0) + 1;
    mem.attempts.set(email, n);
    if (n % 2 === 1) return json({ error: "The service is busy. Please try again." }, 503);
  }
  return null;
}

export async function readBody(req: Request): Promise<Record<string, unknown> | null> {
  try {
    const body = await req.json();
    return body && typeof body === "object" && !Array.isArray(body) ? body : null;
  } catch {
    return null;
  }
}
