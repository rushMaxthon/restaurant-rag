import { describe, expect, it } from "vitest";

import { FALLBACK_CURRENCY } from "@/lib/bangkok-data";
import { storefrontConfigFrom, UNKNOWN_STOREFRONT } from "@/lib/storefront";

/**
 * What one `/app-config` answer becomes for the page that renders from it.
 *
 * Every assertion here is a bug that shipped. The copy fields were literals in
 * `routes/index.tsx`, so six tenants shared one restaurant's page title. The
 * hero image was a bundled photograph of Bangkok Bowl's food, imported by the
 * home, sign-in and sign-up pages, so a Surat dhokla shop opened on a picture
 * of Thai noodles — the most prominent claim on the site, about food that
 * kitchen does not make.
 */
describe("storefrontConfigFrom", () => {
  const restaurant = {
    display_name: "Radhe Dhokla",
    storefront: {
      meta_title: "Radhe Dhokla — Gujarati food delivery in Surat",
      hero_headline: "Radhe Dhokla",
      hero_subcopy: "Soft, steamed dhokla and Gujarati farsan, made fresh through the day.",
    },
    currency: { code: "INR", locale: "en-IN", min_fraction_digits: 0, max_fraction_digits: 2 },
  };

  it("takes the restaurant's own words over the nameless fallback", () => {
    const config = storefrontConfigFrom(restaurant);

    expect(config.name).toBe("Radhe Dhokla");
    expect(config.meta_title).toBe("Radhe Dhokla — Gujarati food delivery in Surat");
    expect(config.currency.code).toBe("INR");
  });

  it("fills the keys the payload did not send", () => {
    // A restaurant halfway through onboarding still has to render, and every
    // key has to be present so no page decides what to do about a missing one.
    const config = storefrontConfigFrom(restaurant);

    expect(config.concierge_intro).toBe(UNKNOWN_STOREFRONT.concierge_intro);
    expect(config.login_blurb).toBe(UNKNOWN_STOREFRONT.login_blurb);
  });

  it("names nobody when the payload names nobody", () => {
    // A MARKETPLACE client is not a restaurant and legitimately sends no
    // storefront at all. Naming one here would put a real restaurant's name on
    // a page that is not theirs.
    const config = storefrontConfigFrom({});

    expect(config.name).toBe(UNKNOWN_STOREFRONT.name);
    expect(config.currency).toBe(FALLBACK_CURRENCY);
    expect(config.cover_image_url).toBeNull();
  });

  describe("the cover image", () => {
    it("is carried through when the restaurant has one", () => {
      const config = storefrontConfigFrom({
        ...restaurant,
        branding: { cover_image_url: "https://cdn.example.com/radhe/hero.jpg" },
      });

      expect(config.cover_image_url).toBe("https://cdn.example.com/radhe/hero.jpg");
    });

    it("is null when the branding field is blank", () => {
      // This is how an unset field actually arrives — "" rather than absent —
      // and an empty `src` renders a broken-image icon where the hero should
      // be. Blank and absent have to mean the same thing.
      for (const value of ["", "   ", null]) {
        expect(
          storefrontConfigFrom({ ...restaurant, branding: { cover_image_url: value } })
            .cover_image_url,
        ).toBeNull();
      }
      expect(storefrontConfigFrom({ ...restaurant, branding: {} }).cover_image_url).toBeNull();
    });

    it("is null when there is no branding at all", () => {
      expect(storefrontConfigFrom(restaurant).cover_image_url).toBeNull();
    });
  });
});
