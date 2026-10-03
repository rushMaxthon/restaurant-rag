"use client";

import { useEffect, useRef, useState } from "react";
import { useMotionValue, useSpring } from "motion/react";

import { cn } from "@/lib/utils";

/**
 * A number that counts up to itself the first time it is scrolled into view.
 *
 * From the Vengeance UI registry (`@vengeanceui/stats-counter`), adapted in
 * three places rather than taken as it came. Each one was measured in the
 * browser, not guessed:
 *
 * 1. **`motion/react`, not `framer-motion`.** The registry declares
 *    `framer-motion`, which is the OLD name for the package this app already
 *    ships as `motion` v13. Installing it would put two copies of the same
 *    animation library in the bundle. The hooks are identical; only the import
 *    path differs.
 *
 * 2. **A plain `IntersectionObserver` instead of Motion's `useInView`.** The
 *    original gate never opened on this page: `isInView` was logged `false`
 *    with the element sitting at y=1522, and it stayed false after the band
 *    was scrolled to, so the spring was never started and every figure sat at
 *    zero. Nothing warned. An observer written here is four lines, has no
 *    version opinion, and is the thing actually being relied on — so it is
 *    worth owning rather than debugging through a wrapper.
 *
 * 3. **It stops at the number when motion is not wanted.** The original always
 *    animates. This app honours `prefers-reduced-motion` everywhere else, and a
 *    rating that ticks upward is exactly the kind of movement somebody turns
 *    that setting on to avoid, so the final value is rendered immediately
 *    instead. Same information, no motion.
 *
 * The observer disconnects after the first crossing on purpose: a figure that
 * re-counts every time it scrolls back past reads as a page that cannot make
 * up its mind.
 */
export function StatsCounter({
  value,
  duration = 1.2,
  prefix = "",
  suffix = "",
  decimals = 0,
  className,
}: {
  value: number;
  duration?: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const motionValue = useMotionValue(0);
  // MILLISECONDS, measured rather than assumed. Passing `duration` straight
  // through made the figure land inside 220ms — the whole count was over
  // before the band had finished arriving — so this version reads a spring's
  // `duration` in ms, and the registry's `* 1000` was right all along.
  const spring = useSpring(motionValue, { duration: duration * 1000, bounce: 0 });
  const [shown, setShown] = useState(0);
  const [animate, setAnimate] = useState(true);

  // Read on mount rather than at module scope: this renders on the server too,
  // where there is no `matchMedia` at all.
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setAnimate(!query.matches);
    apply();
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
  }, []);

  useEffect(() => {
    const node = ref.current;
    if (!node || !animate) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        motionValue.set(value);
        observer.disconnect();
      },
      // A little short of the bottom edge, so the count starts as the band
      // arrives rather than after the reader has already looked at it.
      { rootMargin: "0px 0px -80px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [animate, motionValue, value]);

  useEffect(() => spring.on("change", setShown), [spring]);

  return (
    <span className={cn("tabular-nums", className)} ref={ref}>
      {prefix}
      {(animate ? shown : value).toFixed(decimals)}
      {suffix}
    </span>
  );
}

export default StatsCounter;
