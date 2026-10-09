import { CARD_GAP, GUTTER, inWindow, placeTooltip } from './placement';

const window = { width: 400, height: 800 };

describe('where the tip card goes around a spotlit control', () => {
  it('sits below the control when there is room', () => {
    const target = { x: 100, y: 100, width: 200, height: 48 };
    const place = placeTooltip(target, window, { height: 150 });
    expect(place.side).toBe('below');
    expect(place.top).toBe(100 + 48 + CARD_GAP);
  });

  it('flips above a control near the bottom of the screen', () => {
    const target = { x: 100, y: 700, width: 200, height: 48 };
    const place = placeTooltip(target, window, { height: 150 });
    expect(place.side).toBe('above');
    expect(place.top).toBe(700 - CARD_GAP - 150);
  });

  it('centres the card on the control and keeps it inside the gutters', () => {
    const wide = placeTooltip(
      { x: 0, y: 100, width: 400, height: 48 },
      window,
      { height: 100 },
    );
    expect(wide.left).toBe(GUTTER);
    expect(wide.width).toBe(400 - GUTTER * 2);

    const atEdge = placeTooltip(
      { x: 380, y: 100, width: 20, height: 48 },
      window,
      { height: 100 },
    );
    expect(atEdge.left + atEdge.width).toBeLessThanOrEqual(400 - GUTTER);
    expect(atEdge.left).toBeGreaterThanOrEqual(GUTTER);
  });

  it('points its arrow at the control even when the card is clamped', () => {
    const place = placeTooltip(
      { x: 340, y: 100, width: 40, height: 48 },
      window,
      { height: 100 },
    );
    // The card is clamped to the right gutter; the arrow (relative to the
    // card's left) still lands on the control's centre.
    expect(place.left).toBe(GUTTER);
    expect(place.arrowLeft + place.left).toBe(360);
  });

  it('never puts the card off the top: a tall card above a high control goes below instead', () => {
    const place = placeTooltip(
      { x: 0, y: 40, width: 100, height: 40 },
      window,
      { height: 300 },
    );
    expect(place.side).toBe('below');
  });
});

describe('whether a control is actually on screen', () => {
  it('accepts a control fully inside the window', () => {
    expect(inWindow({ x: 20, y: 100, width: 200, height: 48 }, window)).toBe(
      true,
    );
  });

  it('rejects a control scrolled below the fold or above the top', () => {
    expect(inWindow({ x: 20, y: 790, width: 200, height: 48 }, window)).toBe(
      false,
    );
    expect(inWindow({ x: 20, y: -30, width: 200, height: 48 }, window)).toBe(
      false,
    );
  });

  it('allows the ring padding to touch the edge, but not the control itself', () => {
    expect(inWindow({ x: 0, y: 0, width: 100, height: 40 }, window)).toBe(true);
  });
});
