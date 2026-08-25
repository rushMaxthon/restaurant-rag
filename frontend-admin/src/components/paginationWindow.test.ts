import { describe, expect, it } from 'vitest';
import { buildPageWindow, GAP } from './paginationWindow';

const render = (page: number, total: number) =>
  buildPageWindow(page, total)
    .map((entry) => (entry === GAP ? '…' : String(entry)))
    .join(' ');

describe('buildPageWindow', () => {
  it('lists every page when they all fit', () => {
    expect(render(1, 1)).toBe('1');
    expect(render(3, 5)).toBe('1 2 3 4 5');
    expect(render(4, 7)).toBe('1 2 3 4 5 6 7');
  });

  it('elides the middle once there are more pages than slots', () => {
    expect(render(1, 8)).toBe('1 2 3 4 5 … 8');
    expect(render(20, 40)).toBe('1 … 19 20 21 … 40');
  });

  it('always keeps the first and last page reachable', () => {
    for (const page of [1, 7, 20, 33, 40]) {
      const window = buildPageWindow(page, 40);
      expect(window[0]).toBe(1);
      expect(window[window.length - 1]).toBe(40);
    }
  });

  it('always includes the current page and its neighbours', () => {
    for (const page of [1, 2, 15, 39, 40]) {
      const window = buildPageWindow(page, 40);
      expect(window).toContain(page);
      if (page > 1) expect(window).toContain(page - 1);
      if (page < 40) expect(window).toContain(page + 1);
    }
  });

  it('holds a constant width, so the strip never reflows while paging', () => {
    // The whole point of the window: the old control rendered one button per
    // page and grew without limit.
    const widths = new Set(
      Array.from({ length: 40 }, (_, index) => buildPageWindow(index + 1, 40).length),
    );
    expect([...widths]).toEqual([7]);
  });

  it('never emits two gaps in a row or a gap at either end', () => {
    for (let page = 1; page <= 40; page += 1) {
      const window = buildPageWindow(page, 40);
      expect(window[0]).not.toBe(GAP);
      expect(window[window.length - 1]).not.toBe(GAP);
      window.forEach((entry, index) => {
        if (entry === GAP) expect(window[index + 1]).not.toBe(GAP);
      });
    }
  });
});
