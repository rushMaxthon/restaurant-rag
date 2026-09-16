/**
 * Whether a refusal from the order endpoint is about what is in the cart.
 *
 * The server answers 400 for two different kinds of problem. "The selected
 * size is unavailable for Build Your Own Pizza" is about a line in the cart
 * and can only be fixed there; "Restaurant is currently closed" is about when
 * the order is wanted and is answered on the checkout page itself. The
 * checkout uses this to decide whether to offer the way back to the cart —
 * without it, a stale cart line was a dead end on the last screen before
 * paying.
 *
 * The server does not send a code, so this reads the message: it names the
 * dish (`... for {menu_item.name}`), the cart ("Unavailable items in cart"),
 * or the choice ("Toppings allows at most 2 selections").
 */
export function refusalNeedsCart(message: string, lineNames: string[]): boolean {
  if (!message) return false;
  if (/\bcart\b|selection|customization/i.test(message)) return true;
  return lineNames.some((name) => name.length > 0 && message.includes(name));
}
