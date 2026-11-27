import { expect, test } from "@playwright/test";
import { dobIso, email, inDays, KEY, member } from "./helpers";

const URL = "/portals/harbour/join";

test("a student joins through the page and the student card field appears only for students", async ({ page }) => {
  const mail = email("sofia");
  await page.goto(URL);
  await expect(page.getByTestId("hsc-student-id")).toHaveCount(0);
  await page.getByTestId("hsc-full-name").fill("Sofia Marin");
  await page.getByTestId("hsc-email").fill(mail);
  await page.getByTestId("hsc-phone").fill("07800 345678");
  await page.getByTestId("hsc-date-of-birth").fill(dobIso(19));
  await page.getByTestId("hsc-membership-type").selectOption("student");
  await page.getByTestId("hsc-student-id").fill("uol-482913");
  await page.getByTestId("hsc-start-date").fill(inDays(10));
  await page.getByTestId("hsc-interests-climbing").check();
  await page.getByTestId("hsc-interests-gym").check();
  await page.getByTestId("hsc-emergency-contact-name").fill("Dan Marin");
  await page.getByTestId("hsc-emergency-contact-phone").fill("07900 456789");
  await page.getByTestId("hsc-how-heard").selectOption("friend");
  await page.getByTestId("hsc-accept-terms").check();
  await page.getByTestId("hsc-submit").click();
  await expect(page.getByTestId("hsc-confirmation-ref")).toHaveText(/^HSC-\d{6}$/);
  await expect(page.getByTestId("hsc-confirm-student-id")).toHaveText("UOL482913");
  await expect(page.getByTestId("hsc-confirm-interests")).toHaveAttribute("data-value", "climbing,gym");
});

test("errors show inline, update as they are fixed, and the alert takes focus", async ({ page }) => {
  await page.goto(URL);
  await page.getByTestId("hsc-submit").click();
  await expect(page.getByTestId("hsc-error-summary")).toBeFocused();
  await expect(page.getByTestId("hsc-interests-error")).toBeVisible();
  await page.getByTestId("hsc-membership-type").selectOption("family");
  await expect(page.getByTestId("hsc-family-members-error")).toContainText("how many people");
  await page.getByTestId("hsc-family-members").fill("9");
  await expect(page.getByTestId("hsc-family-members-error")).toContainText("2 to 6");
  await page.getByTestId("hsc-family-members").fill("4");
  await expect(page.getByTestId("hsc-family-members-error")).toHaveCount(0);
});

test.describe("members API", () => {
  test("needs the key", async ({ request }) => {
    expect((await request.post("/api/portals/harbour/members", { data: member() })).status()).toBe(401);
    expect((await request.get("/api/portals/harbour/members?email=a@b.co")).status()).toBe(401);
  });

  test("creates, reads back by number and by email, and refuses a second membership", async ({ request }) => {
    const body = member({ membership_type: "family", family_members: 3 });
    const res = await request.post("/api/portals/harbour/members", { data: body, headers: KEY });
    expect(res.status()).toBe(201);
    const { member_id } = await res.json();
    const one = await request.get(`/api/portals/harbour/members/${member_id}`, { headers: KEY });
    expect((await one.json()).member).toMatchObject({ family_members: 3, phone: "+447800345678", email: body.email });
    const found = await request.get(`/api/portals/harbour/members?email=${encodeURIComponent(body.email.toUpperCase())}`, { headers: KEY });
    expect((await found.json()).members).toHaveLength(1);
    const dup = await request.post("/api/portals/harbour/members", { data: body, headers: KEY });
    expect(dup.status()).toBe(409);
    expect((await dup.json()).member_id).toBe(member_id);
  });

  test("422 lists each field with a reason", async ({ request }) => {
    const res = await request.post("/api/portals/harbour/members", {
      headers: KEY,
      data: member({ date_of_birth: dobIso(12), start_date: inDays(200), interests: [], emergency_contact_phone: "07800 345678", student_id: "X1" }),
    });
    expect(res.status()).toBe(422);
    const errors = (await res.json()).errors as { field: string; message: string }[];
    expect(errors.map((e) => e.field).sort()).toEqual(["date_of_birth", "emergency_contact_phone", "interests", "start_date", "student_id"]);
    expect(errors.every((e) => e.message.length > 5)).toBe(true);
  });

  test("chaos: flaky fails first then succeeds, down always fails", async ({ request }) => {
    const body = member();
    const headers = { ...KEY, "x-portal-chaos": "flaky" };
    expect((await request.post("/api/portals/harbour/members", { data: body, headers })).status()).toBe(503);
    expect((await request.post("/api/portals/harbour/members", { data: body, headers })).status()).toBe(201);
    const down = await request.post("/api/portals/harbour/members", { data: member(), headers: { ...KEY, "x-portal-chaos": "down" } });
    expect(down.status()).toBe(503);
  });

  test("chaos: lost saves the member but the reply never arrives, so a lookup finds it", async ({ request }) => {
    const body = member();
    const res = await request.post("/api/portals/harbour/members", { data: body, headers: { ...KEY, "x-portal-chaos": "lost" } });
    expect(res.status()).toBe(504);
    const found = await request.get(`/api/portals/harbour/members?email=${encodeURIComponent(body.email)}`, { headers: KEY });
    expect((await found.json()).members).toHaveLength(1);
  });
});

test("variant b has no test ids and a different section order", async ({ page }) => {
  await page.goto(`${URL}?variant=b`);
  await expect(page.locator("[data-testid]")).toHaveCount(0);
  const legends = await page.locator("legend").allTextContents();
  expect(legends.slice(0, 3)).toEqual(["You", "Emergency contact", "Plan"]);
  await expect(page.getByRole("button", { name: "Become a member" })).toBeVisible();
});
