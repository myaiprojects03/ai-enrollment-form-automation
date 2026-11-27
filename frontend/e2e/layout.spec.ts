import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const pages = ["/portals/riverside/enroll", "/portals/harbour/join", "/portals/riverside/enroll?variant=b", "/portals/harbour/join?variant=b"];

for (const path of pages) {
  test(`no serious accessibility problems: ${path}`, async ({ page }) => {
    await page.goto(path);
    const first = await new AxeBuilder({ page }).analyze();
    // And with every error showing.
    await page.getByRole("button", { name: /Continue|Next step|Join the club|Become a member/ }).click();
    await expect(page.getByRole("alert").first()).toBeVisible();
    const after = await new AxeBuilder({ page }).analyze();
    const bad = [...first.violations, ...after.violations].filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });

  test(`nothing overflows sideways: ${path}`, async ({ page }) => {
    await page.goto(path);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
}
