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

test("switches to the light theme", async ({ page }) => {
  await open(page);
  await page.locator("#about-btn").click();
  await page.locator('[data-theme-pick="light"]').click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.keyboard.press("Escape");
  await expect(page).toHaveScreenshot("light.png", { mask: masks(page) });
});
