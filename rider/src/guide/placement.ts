/**
 * Where the tip card sits relative to the control it points at. Pure, so it
 * can be tested without a screen: below the control when there is room for
 * the whole card, otherwise above; centred on the control but never past the
 * gutters; and the arrow stays on the control even when the card is clamped.
 */

export type Rect = { x: number; y: number; width: number; height: number };
export type Size = { width: number; height: number };

export const GUTTER = 16;
/** Space between the spotlight ring and the card. */
export const CARD_GAP = 14;
/** The ring drawn around the control, outside its box. */
export const RING_PAD = 8;

export type Placement = {
  side: 'below' | 'above';
  top: number;
  left: number;
  width: number;
  /** Relative to the card's own left edge. */
  arrowLeft: number;
};

export function placeTooltip(
  target: Rect,
  window: Size,
  card: { height: number },
): Placement {
  const width = window.width - GUTTER * 2;
  const centre = target.x + target.width / 2;
  const left = Math.min(
    Math.max(centre - width / 2, GUTTER),
    window.width - GUTTER - width,
  );

  const belowTop = target.y + target.height + CARD_GAP;
  const aboveTop = target.y - CARD_GAP - card.height;
  const fitsBelow = belowTop + card.height <= window.height - GUTTER;
  const fitsAbove = aboveTop >= GUTTER;
  const side: Placement['side'] = fitsBelow || !fitsAbove ? 'below' : 'above';

  return {
    side,
    top: side === 'below' ? belowTop : aboveTop,
    left,
    width,
    arrowLeft: Math.min(Math.max(centre - left, 24), width - 24),
  };
}
