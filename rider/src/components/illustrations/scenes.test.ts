import { dark, light } from '@theme/tokens';
import { highContrast } from '@theme/contrast';

import { fillTemplate, illustrationPalette } from './palette';
import { SCENES } from './scenes';

const themes = [
  ['light', light, 'light'],
  ['dark', dark, 'dark'],
  ['light, high contrast', highContrast(light), 'light'],
  ['dark, high contrast', highContrast(dark), 'dark'],
] as const;

describe('illustrations', () => {
  it.each(themes)(
    'every colour in every scene resolves (%s)',
    (_, colors, mode) => {
      const palette = illustrationPalette(colors, mode);
      for (const [name, template] of Object.entries(SCENES)) {
        const filled = fillTemplate(template, palette);
        expect({ name, left: filled.match(/\{[A-Z]{1,2}\}/g) }).toEqual({
          name,
          left: null,
        });
      }
    },
  );

  it('every scene is one 240 x 160 svg', () => {
    for (const template of Object.values(SCENES)) {
      expect(
        template.startsWith(
          '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 160">',
        ),
      ).toBe(true);
      expect(template.endsWith('</svg>')).toBe(true);
    }
  });

  it('leaves an unknown token visible rather than guessing a colour', () => {
    expect(fillTemplate('<rect fill="{ZZ}"/>', { P: '#f00' })).toBe(
      '<rect fill="{ZZ}"/>',
    );
  });
});
