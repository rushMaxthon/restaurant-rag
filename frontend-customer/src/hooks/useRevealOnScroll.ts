import { useEffect, useRef, type RefObject } from 'react';

/**
 * Reveals one element the first time it enters the viewport.
 *
 * Deliberately does nothing when `IntersectionObserver` is absent. The CSS
 * keeps `.reveal` elements visible unless `<html>` carries `.js-motion`, so a
 * browser without support — or a bundle that never booted — shows plain
 * content rather than a blank page. A reveal that hides content when its
 * machinery fails is worse than no reveal at all.
 *
 * One-shot: it disconnects on first intersection. Left observing, an element
 * re-hides when scrolled past and re-animates on the way back, which reads as
 * flicker rather than as polish.
 */
export function useRevealOnScroll<T extends HTMLElement>(): RefObject<T | null> {
  const ref = useRef<T | null>(null);

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            (entry.target as HTMLElement).classList.add('reveal--visible');
            observer.disconnect();
          }
        }
      },
      // Fires slightly before the element reaches the fold, so the transition
      // is already underway by the time it is actually looked at.
      { rootMargin: '0px 0px -10% 0px', threshold: 0.05 },
    );

    // React attaches `ref.current` during commit, before this effect runs, so
    // in normal use the element is already here. The observer is still built
    // unconditionally so cleanup always has something to disconnect — a
    // consumer that never got an element must not leak an open observer.
    if (ref.current) {
      observer.observe(ref.current);
    }

    return () => observer.disconnect();
  }, []);

  return ref;
}
