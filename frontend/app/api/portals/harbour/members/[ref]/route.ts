import { byRef, json, keyOk } from "@/lib/portals/server";

export async function GET(req: Request, ctx: { params: Promise<{ ref: string }> }) {
  if (!keyOk(req)) return json({ error: "A valid X-Portal-Key header is required." }, 401);
  const row = await byRef("harbour", (await ctx.params).ref);
  return row ? json({ member_id: row.ref, joined_at: row.created_at, member: row.data }) : json({ error: "No such member." }, 404);
}
