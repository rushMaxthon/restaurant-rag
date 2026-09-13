/**
 * The hook adds one class when its element enters the viewport, and then stops
 * observing. Tested against a mocked IntersectionObserver because jsdom has
 * none — which is also the reason the CSS keeps content visible unless
 * `.js-motion` is set: a browser without support must still show the page.
 */

import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useRevealOnScroll } from './useRevealOnScroll';

let triggerIntersect: ((entries: Partial<IntersectionObserverEntry>[]) => void) | null = null;
const disconnect = vi.fn();

beforeEach(() => {
  disconnect.mockClear();
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      constructor(callback: (entries: Partial<IntersectionObserverEntry>[]) => void) {
        triggerIntersect = callback;
      }
      observe() {}
      disconnect = disconnect;
      unobserve() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  triggerIntersect = null;
});

describe('useRevealOnScroll', () => {
  it('returns a ref that starts empty', () => {
    const { result } = renderHook(() => useRevealOnScroll<HTMLDivElement>());

    expect(result.current.current).toBeNull();
  });

  it('adds the visible class once the element intersects', () => {
    const element = document.createElement('div');
    element.className = 'reveal';
    const { result } = renderHook(() => useRevealOnScroll<HTMLDivElement>());
    result.current.current = element;

    triggerIntersect?.([{ isIntersecting: true, target: element }]);

    expect(element.classList.contains('reveal--visible')).toBe(true);
  });

  it('does not add the class while the element is outside the viewport', () => {
    const element = document.createElement('div');
    element.className = 'reveal';
    const { result } = renderHook(() => useRevealOnScroll<HTMLDivElement>());
    result.current.current = element;

    triggerIntersect?.([{ isIntersecting: false, target: element }]);

    expect(element.classList.contains('reveal--visible')).toBe(false);
  });

  /**
   * A reveal is a one-shot. Without this the element re-hides when scrolled
   * past and re-animates on the way back, which reads as flickering.
   */
  it('stops observing after the first reveal', () => {
    const element = document.createElement('div');
    element.className = 'reveal';
    const { result } = renderHook(() => useRevealOnScroll<HTMLDivElement>());
    result.current.current = element;

    triggerIntersect?.([{ isIntersecting: true, target: element }]);

    expect(disconnect).toHaveBeenCalled();
  });

  it('disconnects on unmount so a removed element is not held', () => {
    const { unmount } = renderHook(() => useRevealOnScroll<HTMLDivElement>());

    unmount();

    expect(disconnect).toHaveBeenCalled();
  });
});
