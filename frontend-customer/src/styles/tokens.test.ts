/**
 * Every `var(--token)` in the stylesheets must resolve to a definition.
 *
 * This is not hypothetical. `index.css` documents a token that was
 * "referenced in five places and defined in none, which left every
 * non-vegetarian dot on the menu painted in nothing at all" — CSS fails
 * silently, so a missing custom property is invisible until someone notices
 * the colour is absent.
 *
 * Definitions come from two sources: the `:root` block in the stylesheets, and
 * `applyTheme.ts`, which writes colour and shadow tokens onto the root element
 * at runtime. A token defined only in `applyTheme.ts` is still defined.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '..');

const STYLESHEETS = [
  'index.css',
  'styles/app.css',
  'styles/home.css',
  'styles/screens.css',
  'styles/dish-row.css',
  'styles/motion.css',
].map((file) => join(SRC, file));

function read(path: string): string {
  return readFileSync(path, 'utf8');
}

function definedTokens(): Set<string> {
  const defined = new Set<string>();

  for (const sheet of STYLESHEETS) {
    for (const match of read(sheet).matchAll(/^\s*(--[a-z0-9-]+)\s*:/gim)) {
      defined.add(match[1]);
    }
  }

  // applyTheme publishes colour and shadow tokens at runtime.
  for (const match of read(join(SRC, 'theme/applyTheme.ts')).matchAll(/'(--[a-z0-9-]+)'/g)) {
    defined.add(match[1]);
  }

  return defined;
}

function referencedTokens(): Map<string, string[]> {
  const referenced = new Map<string, string[]>();

  for (const sheet of STYLESHEETS) {
    for (const match of read(sheet).matchAll(/var\(\s*(--[a-z0-9-]+)/g)) {
      const token = match[1];
      referenced.set(token, [...(referenced.get(token) ?? []), sheet]);
    }
  }

  return referenced;
}

describe('CSS custom properties', () => {
  it('defines every token the stylesheets reference', () => {
    const defined = definedTokens();
    const undefinedTokens = [...referencedTokens().entries()]
      .filter(([token]) => !defined.has(token))
      .map(([token, sheets]) => `${token} (used in ${sheets.length} file(s))`);

    expect(undefinedTokens).toEqual([]);
  });

  it('defines the typography tokens the app depends on', () => {
    const defined = definedTokens();

    expect(defined.has('--font-ui')).toBe(true);
    expect(defined.has('--font-display')).toBe(true);
  });
});
