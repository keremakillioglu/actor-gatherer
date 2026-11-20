// The dashboard's panel (page.html: "ag's settings"): ag's settings and this page's, the theme among them.
import { expect, test } from "./test";
import { masks, open } from "./home";

test("opens from the logo, showing the model the home has set", async ({ page }) => {
  await open(page);
  await page.locator("#about-btn").click();
  await expect(page.locator("#about")).toBeVisible();
  await expect(page.locator("#cfg-model-name")).toHaveValue("claude-code/sonnet");
  await expect(page.locator("#about")).toHaveScreenshot("settings.png", { mask: masks(page) });
});

test("System follows the system's look, and as it changes", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await open(page);
  await page.locator("#about-btn").click();
  await page.locator('[data-theme-pick="system"]').click();
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "light");
  const page_ = await html.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--page").trim());
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(html).toHaveAttribute("data-theme", "dark");
  await expect
    .poll(() => html.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--page").trim()))
    .not.toBe(page_);
});

test("switches to the light theme", async ({ page }) => {
  await open(page);
  await page.locator("#about-btn").click();
  await page.locator('[data-theme-pick="light"]').click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.keyboard.press("Escape");
  await expect(page).toHaveScreenshot("light.png", { mask: masks(page) });
});
