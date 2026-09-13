/**
 * Every file a `@font-face` names must exist in `public/`.
 *
 * A missing font file produces no error anywhere: the browser silently uses
 * the next family in the stack, so the page renders in the fallback and looks
 * plausible. Without this test, a bad path or a file left out of a commit is
 * caught only by someone noticing the letterforms changed.
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '..');
const PUBLIC_DIR = join(SRC, '..', 'public');

const FONT_CSS = join(SRC, 'styles/fonts.css');

describe('@font-face declarations', () => {
  it('declares at least one face', () => {
    const css = readFileSync(FONT_CSS, 'utf8');

    expect(css).toContain('@font-face');
  });

  it('points every src at a file that exists in public/', () => {
    const css = readFileSync(FONT_CSS, 'utf8');
    const urls = [...css.matchAll(/url\(\s*['"]?([^'")]+)['"]?\s*\)/g)].map((m) => m[1]);

    expect(urls.length).toBeGreaterThan(0);

    const missing = urls.filter((url) => !existsSync(join(PUBLIC_DIR, url.replace(/^\//, ''))));

    expect(missing).toEqual([]);
  });

  it('uses font-display: swap so headlines never blank while loading', () => {
    const css = readFileSync(FONT_CSS, 'utf8');

    expect(css).toMatch(/font-display:\s*swap/);
  });
});
