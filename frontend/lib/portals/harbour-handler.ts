import "server-only";
import { str, todayUtc } from "./common";
import { normaliseHarbour, validateHarbour } from "./harbour";
import { beforeSave, byEmail, chaosOf, json, readBody, save } from "./server";

/** Shared by the public join page and the keyed members API. */
export async function createMember(req: Request): Promise<Response> {
  const body = await readBody(req);
  if (!body) return json({ error: "Send the member as a JSON object." }, 400);
  const errors = validateHarbour(body, todayUtc());
  if (errors.length) return json({ errors }, 422);
  const data = normaliseHarbour(body);
  const email = str(data.email);
  const existing = await byEmail("harbour", email);
  if (existing.length) return json({ error: "This email already has a membership.", member_id: existing[0].ref }, 409);
  const chaos = chaosOf(req);
  const early = await beforeSave(chaos, email);
  if (early) return early;
  const row = await save("harbour", email, data);
  if (chaos === "lost") return json({ error: "Gateway timeout" }, 504);
  return json({ member_id: row.ref, joined_at: row.created_at, member: row.data }, 201);
}
