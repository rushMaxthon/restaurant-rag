import { cn } from "@/lib/utils";

/**
 * The vegetarian / non-vegetarian mark.
 *
 * A square outline with a filled dot inside it, which is the form this is
 * legally required to take on packaged food in India and therefore the form
 * every customer here already reads. It is deliberately NOT themed: these are
 * the only two colours on the storefront a restaurant cannot change, because
 * recolouring a food-safety mark to match a brand makes it mean something
 * else.
 *
 * `className` exists so a caller can set its size. On the menu it leads every
 * row and is sized up accordingly; elsewhere it stays an annotation.
 */
export function VegMark({ className, veg }: { className?: string; veg: boolean }) {
  return (
    <span
      aria-label={veg ? "Vegetarian" : "Non-vegetarian"}
      className={cn(veg ? "veg-mark" : "nonveg-mark", className)}
    >
      <i />
    </span>
  );
}
