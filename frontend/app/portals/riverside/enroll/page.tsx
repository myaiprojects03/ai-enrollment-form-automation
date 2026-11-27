import Wizard from "./Wizard";

type Search = Promise<Record<string, string | string[] | undefined>>;

/** ?variant=b serves a reworded, reordered page without test ids (to exercise self-healing locators).
 *  ?chaos=slow|flaky|down|lost|captcha simulates trouble. */
export default async function EnrollPage({ searchParams }: { searchParams: Search }) {
  const q = await searchParams;
  const variant = q.variant === "b" ? "b" : "a";
  const chaos = typeof q.chaos === "string" ? q.chaos : "";
  return <Wizard variant={variant} chaos={chaos} />;
}
