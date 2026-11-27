import JoinForm from "./JoinForm";

type Search = Promise<Record<string, string | string[] | undefined>>;

/** ?variant=b rewords and reorders the form without test ids; ?chaos=slow|flaky|down|lost|captcha simulates trouble. */
export default async function JoinPage({ searchParams }: { searchParams: Search }) {
  const q = await searchParams;
  return <JoinForm variant={q.variant === "b" ? "b" : "a"} chaos={typeof q.chaos === "string" ? q.chaos : ""} />;
}
