import { byRef, json, keyOk } from "@/lib/portals/server";

export async function GET(req: Request, ctx: { params: Promise<{ ref: string }> }) {
  if (!keyOk(req)) return json({ error: "A valid X-Portal-Key header is required." }, 401);
  const row = await byRef("riverside", (await ctx.params).ref);
  return row ? json({ ref: row.ref, created_at: row.created_at, application: row.data }) : json({ error: "No such application." }, 404);
}
