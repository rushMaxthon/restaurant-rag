import { describe, expect, it } from "vitest";
import { refusalNeedsCart } from "./order-refusal";

/**
 * The messages here are the server's own, from
 * backend/app/services/menu_item_customizations.py and orders.py. If one of
 * them is reworded there, this is where the checkout's "change it in your
 * cart" link quietly stops appearing.
 */
const lines = ["Build Your Own Pizza", "Thai Chilli Basil Rice"];

describe("a refusal the cart can fix", () => {
  it("names the dish", () => {
    expect(
      refusalNeedsCart("The selected size is unavailable for Build Your Own Pizza.", lines),
    ).toBe(true);
    expect(refusalNeedsCart("Select a size for Build Your Own Pizza.", lines)).toBe(true);
  });

  it("names the cart", () => {
    expect(
      refusalNeedsCart("Unavailable items in cart: Green Curry, Pad Thai", lines),
    ).toBe(true);
    expect(refusalNeedsCart("Duplicate menu items are not allowed in the cart", lines)).toBe(true);
  });

  it("names the choice, even without the dish", () => {
    expect(refusalNeedsCart("Toppings allows at most 2 selections.", lines)).toBe(true);
    expect(refusalNeedsCart("Toppings requires at least one selection.", lines)).toBe(true);
    expect(
      refusalNeedsCart("An unavailable customization was selected for Green Curry.", lines),
    ).toBe(true);
  });
});

describe("a refusal answered on the checkout page", () => {
  it("is about when, not what", () => {
    expect(refusalNeedsCart("Restaurant is currently closed", lines)).toBe(false);
    expect(refusalNeedsCart("Restaurant location is currently closed", lines)).toBe(false);
    expect(refusalNeedsCart("Requested time is outside opening hours", lines)).toBe(false);
  });

  it("is nothing at all", () => {
    expect(refusalNeedsCart("", lines)).toBe(false);
    // An empty line name must not match every message.
    expect(refusalNeedsCart("Restaurant is currently closed", [""])).toBe(false);
  });
});
