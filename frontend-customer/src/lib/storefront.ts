import { useLoaderData } from "@tanstack/react-router";

import {
  FALLBACK_CURRENCY,
  formatMoney,
  formatRoundedMoney,
  type CurrencyFormat,
  type Money,
} from "@/lib/bangkok-data";

/**
 * This restaurant's own words.
 *
 * Page title, meta description and hero copy used to be string literals in
 * `routes/index.tsx` and `routes/__root.tsx`, so all six tenants shared one
 * restaurant's name — in every browser tab, every link preview and every
 * search result. The strings now come from the restaurant's own record,
 * resolved from the address the request arrived on.
 *
 * The server half lives in `storefront.server.ts`, because reading the
 * incoming request is something only the server can do.
 */
export type StorefrontConfig = StorefrontCopy & {
  currency: CurrencyFormat;
  /**
   * The restaurant's own hero photograph, or null.
   *
   * It rides the root loader alongside the copy because a hero image is the
   * largest thing on the page and a client-side fetch for it would mean every
   * storefront painting an empty band first.
   */
  cover_image_url: string | null;
  /** The restaurant's own mark, when it has uploaded one. */
  logo_url: string | null;
  /**
   * The id of the typeface this restaurant chose, from the backend allowlist.
   *
   * On the root loader rather than fetched after hydration because a font is
   * the one branding decision that must be settled before the first paint:
   * resolved later, every visitor sees the page re-set itself in a different
   * family. `lib/fonts.ts` turns this into the stylesheet to load.
   */
  font_family: string | null;
  /**
   * Where this kitchen is and how to reach it, with the unfilled parts absent.
   *
   * On the root loader rather than fetched per page because the footer that
   * reads it is on every page, and because a search engine reading a
   * restaurant's address wants it in the first HTML response.
   *
   * An empty object is a correct and common answer — onboarding collects a
   * name and an owner, not an address — so every surface reading this renders
   * nothing rather than rendering a placeholder.
   */
  contact: StorefrontContact;
  /**
   * What this restaurant says about itself at length, and the questions it
   * has answered. Both lists, both usually empty.
   *
   * On the root loader with the rest because the home page renders it and a
   * search engine reads the FAQ out of the first response — fetched after
   * hydration, neither would arrive in time to matter.
   *
   * **Nothing here is ever derived.** An empty list means the owner has not
   * written that part, and the page shows nothing rather than filling it with
   * words we wrote under their name.
   */
  brand: StorefrontBrand;
};

/** One headed section of a restaurant's own description. */
export type BrandSection = {
  heading: string;
  body: string;
  bullets?: string[];
};

/** One question a customer asks before a first order, and its answer. */
export type BrandFaq = {
  question: string;
  answer: string;
};

/**
 * One figure worth a tile, and where it came from.
 *
 * `note` is attribution. A rating a restaurant earned on a listing site is a
 * real fact and not this platform's measurement — shown bare it reads as ours,
 * which is a claim nobody here is entitled to make.
 */
export type BrandHighlight = {
  value: string;
  label: string;
  note?: string;
};

export type StorefrontBrand = {
  about_sections: BrandSection[];
  faqs: BrandFaq[];
  /**
   * The YEAR, never a duration. "26 years in business" is what the listing
   * sites publish, and it is correct for one year and silently wrong after.
   * `yearsTrading` does the subtraction at render time.
   */
  established_year: number | null;
  specialities: string[];
  highlights: BrandHighlight[];
};

export const NO_BRAND: StorefrontBrand = {
  about_sections: [],
  faqs: [],
  established_year: null,
  specialities: [],
  highlights: [],
};

/**
 * How long this kitchen has been trading, from the year it opened.
 *
 * Returns null for a year nobody set, and for one that cannot be true — a
 * storefront must never print "Baking for -4 years" because somebody typed
 * next year's date into a form. The backend refuses those on the way in; this
 * is the second line, because the column is JSONB and has outlived its rules
 * before.
 */
export function yearsTrading(
  establishedYear: number | null | undefined,
  now: Date = new Date(),
): number | null {
  if (!establishedYear) return null;
  const years = now.getFullYear() - establishedYear;
  return years > 0 ? years : null;
}

/**
 * The subset of `restaurants`' address columns the backend judged real.
 *
 * Every field is optional for one reason: the backend OMITS a key it has not
 * really got, instead of sending the onboarding placeholder. So `undefined`
 * here means "nobody has filled this in", and there is no value to check
 * against — which is what keeps "Pending restaurant setup" off a live footer.
 */
export type StorefrontContact = {
  /** Street, city, state and postal code as one line, assembled server-side. */
  address?: string;
  address_line_1?: string;
  address_line_2?: string;
  city?: string;
  state?: string;
  postal_code?: string;
  country?: string;
  phone?: string;
};

export type StorefrontCopy = {
  /**
   * The restaurant's name, for page titles like "Your cart — Radhe Dhokla".
   *
   * Separate from `hero_headline`, which starts as the name but is the one
   * field an owner is most likely to rewrite into a slogan — and "Your cart —
   * Wok this way" is not a page title.
   */
  name: string;
  meta_title: string;
  meta_description: string;
  og_title: string;
  og_description: string;
  hero_headline: string;
  hero_subcopy: string;
  concierge_intro: string;
  login_blurb: string;
};

/**
 * What the page says when the backend cannot be reached.
 *
 * Deliberately nameless. A storefront that cannot reach its API has no way to
 * know which restaurant it is, and naming one — the old behaviour, and the
 * reason this file exists — puts a real restaurant's name on a page that is
 * not theirs. "Order online" tells a crawler nothing, and telling it nothing
 * beats telling it something false.
 */
export const UNKNOWN_STOREFRONT: StorefrontCopy = {
  name: "this kitchen",
  meta_title: "Order online",
  meta_description: "Browse the menu and order online.",
  og_title: "Order online",
  og_description: "Browse the menu and order online.",
  hero_headline: "Order online",
  hero_subcopy: "Browse the menu and order online.",
  concierge_intro: "Ask me anything about the menu.",
  login_blurb: "Sign in to place your order.",
};

/** The shape `/app-config` answers with, as far as a storefront cares. */
export type AppConfigPayload = {
  display_name?: string;
  storefront?: Partial<StorefrontCopy>;
  currency?: CurrencyFormat;
  branding?: {
    cover_image_url?: string | null;
    logo_url?: string | null;
    font_family?: string | null;
  };
  contact?: StorefrontContact;
  brand?: Partial<StorefrontBrand>;
};

/**
 * One `/app-config` answer, turned into what the root loader carries.
 *
 * Pure, and separate from the server function that fetches it, so the
 * decisions in it can be tested: which fields are merged rather than trusted
 * wholesale, and what counts as "this restaurant has no cover image".
 */
export function storefrontConfigFrom(payload: AppConfigPayload): StorefrontConfig {
  return {
    // Merged rather than trusted wholesale: the backend fills every key for a
    // restaurant, but a MARKETPLACE client legitimately sends none.
    ...UNKNOWN_STOREFRONT,
    name: payload.display_name || UNKNOWN_STOREFRONT.name,
    ...(payload.storefront ?? {}),
    currency: payload.currency ?? FALLBACK_CURRENCY,
    // An unset branding field arrives as "", which is not a URL. Left as-is it
    // would render an <img> with an empty src — a broken-image icon where the
    // hero should be — so blank and absent both mean "no cover", and the hero
    // falls back to this restaurant's brand colour rather than another
    // restaurant's food.
    cover_image_url: payload.branding?.cover_image_url?.trim() || null,
    // Blank and absent both mean "no logo", so the header draws the monogram.
    logo_url: payload.branding?.logo_url?.trim() || null,
    // Blank and absent both mean "unset", which `resolveFonts` reads as the
    // platform default rather than as a family called "".
    font_family: payload.branding?.font_family?.trim() || null,
    // Taken as given rather than defaulted: the backend already decided which
    // keys are real, and inventing one here would put it back.
    contact: payload.contact ?? {},
    // Each half defaulted separately: a payload carrying sections but no
    // questions is a normal answer, not a malformed one.
    // Each field defaulted separately: a payload carrying sections but no
    // questions is a normal answer, not a malformed one — and a client built
    // against an older backend, which is every mobile app between releases,
    // simply will not see the fields that backend has never heard of.
    brand: {
      about_sections: payload.brand?.about_sections ?? [],
      faqs: payload.brand?.faqs ?? [],
      established_year: payload.brand?.established_year ?? null,
      specialities: payload.brand?.specialities ?? [],
      highlights: payload.brand?.highlights ?? [],
    },
  };
}

/**
 * This restaurant's address and phone number, from anywhere in the tree.
 *
 * A read of the root loader, like `useStorefrontCover` — these strings were in
 * the HTML before it was sent, so the footer on every page costs nothing.
 */
/**
 * This restaurant's own description and answered questions.
 *
 * A read of the root loader, like the contact details: these were in the HTML
 * before it was sent, so the home page pays nothing for them.
 */
export function useStorefrontBrand(): StorefrontBrand {
  const data = useLoaderData({ from: "__root__" }) as StorefrontConfig | undefined;
  return data?.brand ?? NO_BRAND;
}

export function useStorefrontContact(): StorefrontContact {
  const data = useLoaderData({ from: "__root__" }) as StorefrontConfig | undefined;
  return data?.contact ?? {};
}

/** The meta tags a storefront's copy produces, shared by every route. */
export function storefrontMeta(copy: StorefrontCopy) {
  return [
    { title: copy.meta_title },
    { name: "description", content: copy.meta_description },
    { name: "author", content: copy.hero_headline },
    { property: "og:title", content: copy.og_title },
    { property: "og:description", content: copy.og_description },
    { property: "og:type", content: "website" },
    { name: "twitter:card", content: "summary_large_image" },
  ];
}

/**
 * The copy the root route resolved, from anywhere in the tree.
 *
 * A read rather than a fetch: these strings were in the HTML before it was
 * sent, so a page that shows them should not pay for them again. Read off the
 * root route by id rather than imported from it, which would be a cycle —
 * `__root.tsx` imports this module.
 */
export function useStorefrontCopy(): StorefrontCopy {
  const data = useLoaderData({ from: "__root__" }) as StorefrontCopy | undefined;
  return data ?? UNKNOWN_STOREFRONT;
}

/**
 * A price formatter bound to what THIS restaurant charges in.
 *
 * A hook rather than a module-level "current currency", which would be shared
 * across every request the server is rendering at once — one tenant's rupees
 * would end up on another tenant's dollars, and only under load. The currency
 * rides the root loader, so it is already correct in the server-rendered HTML.
 */
/**
 * This restaurant's own hero photograph, or null when it has not set one.
 *
 * Null is a real answer, not a missing one. Three pages used to import a
 * bundled photograph of Bangkok Bowl's pad thai and show it on every tenant's
 * site, so a Surat dhokla shop's home page, login page and sign-up page all
 * opened on a picture of Thai noodles. Showing a different restaurant's food
 * is worse than showing none: it is a claim about what this kitchen makes.
 */
export function useStorefrontCover(): string | null {
  const data = useLoaderData({ from: "__root__" }) as StorefrontConfig | undefined;
  return data?.cover_image_url ?? null;
}

/**
 * This restaurant's logo, or null when it has not uploaded one.
 *
 * Read from the root loader like the cover, so the header draws the real mark
 * in the first HTML response rather than swapping a monogram for it after
 * hydration. Null is the normal state and has its own answer — the monogram
 * built from the restaurant's own name — rather than a placeholder image.
 */
export function useStorefrontLogo(): string | null {
  const data = useLoaderData({ from: "__root__" }) as StorefrontConfig | undefined;
  return data?.logo_url ?? null;
}

export function useMoney(): (value: Money | number) => string {
  const data = useLoaderData({ from: "__root__" }) as StorefrontConfig | undefined;
  const currency = data?.currency ?? FALLBACK_CURRENCY;
  return (value) => formatMoney(value, currency);
}

/**
 * `useMoney` for prose rather than for prices — see `formatRoundedMoney`.
 * The craving chips are the callers: they name a budget, not a price.
 */
export function useRoundedMoney(): (value: Money | number) => string {
  const data = useLoaderData({ from: "__root__" }) as StorefrontConfig | undefined;
  const currency = data?.currency ?? FALLBACK_CURRENCY;
  return (value) => formatRoundedMoney(value, currency);
}

/**
 * The currency code this storefront charges in, for the few places that need
 * the code itself rather than a formatted amount — the checkout's postal-code
 * label is the one today. Same loader, same per-request safety as `useMoney`.
 */
export function useCurrencyCode(): string {
  const data = useLoaderData({ from: "__root__" }) as StorefrontConfig | undefined;
  return (data?.currency ?? FALLBACK_CURRENCY).code;
}

/**
 * A page title for a route inside the storefront: "Your cart — Radhe Dhokla".
 *
 * Takes the copy from the route's OWN loader rather than reaching up to the
 * root's. A child route's `head` runs while the root loader is still pending —
 * `matches` carries the root with `status: "pending"` and no data — so the
 * parent's result genuinely is not available yet, and reading it produced
 * "Your cart — this kitchen" on every page. The server fn each route calls is
 * cached per host, so asking again costs nothing.
 *
 * Eleven routes used to spell "Bangkok Bowl" into their own titles, so eleven
 * pages of every tenant's website were named after one restaurant.
 */
export function pageMeta(copy: StorefrontCopy | undefined, page: string, description: string) {
  const title = `${page} — ${(copy ?? UNKNOWN_STOREFRONT).name}`;
  return [
    { title },
    { name: "description", content: description },
    { property: "og:title", content: title },
    { property: "og:description", content: description },
    { property: "og:type", content: "website" },
  ];
}
