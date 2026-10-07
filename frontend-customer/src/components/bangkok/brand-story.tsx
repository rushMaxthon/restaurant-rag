import { Link } from "@tanstack/react-router";
import { ArrowRight, Check, Quote } from "lucide-react";

import { BrandRail } from "@/components/bangkok/brand-facts";
import { useStorefrontBrand, type BrandSection } from "@/lib/storefront";
import { jsonLd } from "@/lib/json-ld";

/**
 * What this kitchen says about itself, in its own words.
 *
 * A single-restaurant storefront IS that restaurant's website, and the home
 * page's job is the one question a menu cannot answer: who are these people,
 * and why order from them rather than from anyone else. The dishes have their
 * own page; this is what a first-time visitor reads before they get there.
 *
 * **Every word is the restaurant's own, written in the operator panel**
 * (`/website`), stored on `restaurants.brand`, and carried on `/app-config` so
 * it is in the first HTML response rather than arriving after hydration.
 *
 * **Nothing is derived, and that is the whole design.** The short copy in
 * `restaurant_storefront.py` fills its gaps from the restaurant's name,
 * cuisine and city, because a tenant onboarded five minutes ago still needs a
 * page title. Here a generated paragraph would be a claim about a real
 * business's standards that nobody at that business made — and it would be the
 * same paragraph under every restaurant's name, which is precisely the bug
 * that whole subsystem exists to have fixed. An owner who has written nothing
 * gets nothing: every block below renders `null`, and the page closes up
 * around it.
 *
 * **The layout follows what was written, rather than the owner writing to fit
 * a layout.** Three identical cards in a row was the first version, and it
 * made a paragraph of history, a list of services and a statement about
 * ingredients look like the same kind of thing — so the page had no shape and
 * nothing to read first. The sections are now classified by what is IN them:
 *
 * - the first prose section becomes the lead story, set beside photographs of
 *   this kitchen's own food;
 * - any section carrying bullets becomes a grid of what they offer, because a
 *   list wants to be read as a list;
 * - every other prose section becomes a standalone statement.
 *
 * That holds for a restaurant with one section and for one with eight, in
 * whatever order they were written, which is what makes it the same component
 * for every tenant on the platform.
 */
/**
 * How the owner's sections divide up, classified by what is IN them.
 *
 * Classified rather than positional: an owner who leads with their list of
 * services still gets a lead story, and one who writes nothing but prose gets
 * no empty grid.
 */
function useClassifiedSections() {
  const { about_sections: sections } = useStorefrontBrand();
  const prose = sections.filter((section) => !hasBullets(section) && bodyOf(section).length > 0);
  const [lead, ...statements] = prose;
  return { lead, statements, listed: sections.filter(hasBullets) };
}

/**
 * The lead story: the owner's first paragraph, set beside their own food.
 *
 * The three blocks below are separate components rather than one `BrandStory`
 * because the HOME PAGE owns the running order, and it needs to put things
 * between them — the figures belong straight after the story that earns them,
 * and the photographs belong before the list of services rather than after a
 * closing statement. One component emitting all three in a fixed sequence
 * meant the page read story → services → statement → numbers, with the single
 * most persuasive fact on the page arriving fourth.
 */
export function BrandStory() {
  const { lead } = useClassifiedSections();

  return (
    <>
      {lead && (
        // The anchor the hero's second button points at. `scroll-margin-top`
        // on it clears the sticky header; see `.brand-lead` in polish.css.
        <section className="brand-lead" id="story">
          <div className="page-pad section-pad brand-lead__inner">
            {/* The shop's facts, pinned, with the story moving beside them.
                They used to sit in a band of their own further down, which
                meant the answer to "who is this" had scrolled away by the
                time you finished reading why. */}
            <BrandRail />

            <div className="brand-lead__copy">
              {/* The heading is the OWNER'S, not the restaurant's name. The
                  name was here first and it read as a mistake: for any tenant
                  who has not rewritten `hero_headline` into a slogan — which
                  is every tenant on the day they are onboarded — the hero
                  above says exactly the same words in 64px type. The one line
                  of display type on this block is a line the owner can change
                  in `/website`.

                  The "Our story" label that was here is gone. A tracked-out
                  capitalised word above a heading is the commonest tell of a
                  templated page, and this one announced a story that the
                  heading underneath was already telling. */}
              <h2 className="font-display brand-lead__title reveal-wipe">
                <span>{lead.heading}</span>
              </h2>
              <div className="brand-lead__body">{paragraphs(lead)}</div>
              <Link className="brand-lead__cta" to="/menu">
                See the full menu <ArrowRight aria-hidden="true" />
              </Link>
            </div>

            {/* The photographs that were here have gone to the gallery
                further down, which was already showing the same three. Two
                copies of a kitchen's best pictures on one page made both
                look like filler, and the column they occupied is worth more
                to the facts now in it. */}
          </div>
        </section>
      )}
    </>
  );
}

/** What the restaurant offers, from any section the owner gave bullets to. */
export function BrandOffer() {
  const { listed } = useClassifiedSections();

  return (
    <>
      {listed.map((section, index) => (
        <section className="brand-offer" key={`${section.heading}-${index}`}>
          <div className="page-pad section-pad brand-offer__inner">
            <h2 className="font-display brand-offer__title reveal-wipe">
              <span>{section.heading}</span>
            </h2>
            {bodyOf(section).length > 0 && (
              <div className="brand-offer__body">{paragraphs(section)}</div>
            )}
            <ul className="brand-offer__grid reveal-group">
              {(section.bullets ?? []).map((bullet, at) => (
                <li className="brand-offer__item" key={at}>
                  {/* One consistent mark, deliberately. Picking an icon per
                      bullet would mean guessing what the sentence is about,
                      and a wrong glyph beside somebody's own words is worse
                      than no glyph. */}
                  <span className="brand-offer__tick" aria-hidden="true">
                    <Check />
                  </span>
                  <span>{bullet}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      ))}
    </>
  );
}

/** Any remaining prose section, as a statement in its own band. */
export function BrandStandards() {
  const { statements } = useClassifiedSections();

  return (
    <>
      {statements.length > 0 && (
        <section className="brand-standards">
          <div className="page-pad section-pad brand-standards__inner">
            {statements.map((section, index) => (
              <article
                className="brand-standards__card reveal-left"
                key={`${section.heading}-${index}`}
              >
                <Quote className="brand-standards__mark" aria-hidden="true" />
                <h2 className="font-display brand-standards__title">{section.heading}</h2>
                <div className="brand-standards__body">{paragraphs(section)}</div>
              </article>
            ))}
          </div>
        </section>
      )}
    </>
  );
}

const hasBullets = (section: BrandSection) => (section.bullets?.length ?? 0) > 0;

const bodyOf = (section: BrandSection) => (section.body ?? "").trim();

/**
 * The owner's paragraph breaks, kept.
 *
 * `restaurant_brand.py` stores them deliberately, unlike the short copy, and
 * throwing them away here would turn three paragraphs into one wall. Never
 * `dangerouslySetInnerHTML`: this is somebody's typing, not markup.
 */
function paragraphs(section: BrandSection) {
  return bodyOf(section)
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)
    .map((paragraph, at) => <p key={at}>{paragraph}</p>);
}

/**
 * The questions people ask before ordering, answered.
 *
 * `<details>` rather than a hand-rolled accordion, for three reasons that all
 * matter here: the answers are in the DOM whether or not anything opens, so a
 * crawler and a reader using find-in-page both get them; it needs no
 * JavaScript, so it works in the server-rendered HTML before hydration; and
 * the keyboard and screen-reader behaviour is the browser's rather than ours
 * to get wrong.
 *
 * The first one is open on arrival. A wall of identical closed rows reads as a
 * list of links rather than as answers, and one open row shows what the rest
 * are.
 */
export function BrandFaqs() {
  const { faqs } = useStorefrontBrand();

  if (faqs.length === 0) return null;

  return (
    <section className="brand-faqs">
      <div className="page-pad section-pad brand-faqs__inner">
        <p className="eyebrow">Before you order</p>
        <h2 className="font-display brand-faqs__title reveal-wipe">
          <span>Questions people ask</span>
        </h2>

        <div className="brand-faqs__list reveal-group">
          {faqs.map((faq, index) => (
            <details className="brand-faq" key={`${faq.question}-${index}`} open={index === 0}>
              <summary>{faq.question}</summary>
              <div className="brand-faq__answer">
                {faq.answer
                  .split(/\n{2,}/)
                  .map((paragraph) => paragraph.trim())
                  .filter(Boolean)
                  .map((paragraph, at) => (
                    <p key={at}>{paragraph}</p>
                  ))}
              </div>
            </details>
          ))}
        </div>
      </div>

      {/* The same answers in the form a search engine reads, built from the
          same array so the page and the listing cannot drift apart. A
          `FAQPage` is one of the few structured-data types that still earns a
          richer result, and this is the only page on the site that can
          honestly claim one. */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          // `jsonLd`, never `JSON.stringify`: the answers are an owner's
          // typing, and a raw `</script>` in one would run as script.
          __html: jsonLd({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            mainEntity: faqs.map((faq) => ({
              "@type": "Question",
              name: faq.question,
              acceptedAnswer: { "@type": "Answer", text: faq.answer },
            })),
          }),
        }}
      />
    </section>
  );
}
