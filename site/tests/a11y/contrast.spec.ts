import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const A11Y_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] as const;
const MODES = [
  { name: 'default light', theme: 'light', contrast: false },
  { name: 'dark', theme: 'dark', contrast: false },
  { name: 'enhanced contrast', theme: 'light', contrast: true },
] as const;
const PAGES = ['/', '/protocols/venus/'] as const;

for (const mode of MODES) {
  for (const width of [375, 1280] as const) {
    for (const path of PAGES) {
      test(`${mode.name} has no serious or critical contrast violations at ${width}px on ${path}`, async ({
        page,
      }) => {
        await page.setViewportSize({ width, height: 812 });
        await page.addInitScript(({ theme, contrast }) => {
          localStorage.setItem('rd-theme', theme);
          if (contrast) localStorage.setItem('rd-prefer-contrast', '1');
          else localStorage.removeItem('rd-prefer-contrast');
        }, mode);
        await page.goto(path);
        if (path === '/')
          await expect(page.locator('[role="table"][aria-label="Protocols"]')).toBeVisible();
        else await expect(page.locator('main#main')).toBeVisible();
        await expect(page.locator('html')).toHaveAttribute('data-theme', mode.theme);
        if (mode.contrast)
          await expect(page.locator('html')).toHaveAttribute('data-prefer-contrast', '');
        else await expect(page.locator('html')).not.toHaveAttribute('data-prefer-contrast');

        const results = await new AxeBuilder({ page }).withTags([...A11Y_TAGS]).analyze();
        const violations = results.violations.filter(
          (violation) => violation.impact === 'serious' || violation.impact === 'critical',
        );
        expect(
          violations,
          violations.map((violation) => `${violation.id}: ${violation.description}`).join('\n'),
        ).toEqual([]);
      });
    }
  }
}
