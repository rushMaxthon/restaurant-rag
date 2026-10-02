import { useStorefrontBrand, useStorefrontCopy } from "@/lib/storefront";

/**
 * What this kitchen says about itself, in its own words.
 *
 * A single-restaurant storefront is that restaurant's website, and a website
 * that opens on a menu and ends at a menu is a form. This is the part a
 * customer reads before a FIRST order — who this is, what they are known for,
 * and the handful of questions everybody asks — which is exactly the moment
 * the decision to trust an unfamiliar kitchen gets made.
 *
 * **Every word is the restaurant's own, written in the operator panel**
 * (`/website`), stored on `restaurants.brand`, and carried on `/app-config` so
 * it is in the first HTML response rather than arriving after hydration.
 *
 * **Nothing is derived, and that is the whole design.** The short copy in
 * `restaurant_storefront.py` fills its gaps from the restaurant's name,
 * cuisine and city, because a tenant onboarded five minutes ago still needs a
 * page title. Here a generated paragraph would be a claim about a real
 * business's standards that nobody at that business made — and it would be
 * the same paragraph under every restaurant's name, which is precisely the bug
 * that whole subsystem exists to have fixed. An owner who has written nothing
 * gets nothing: both components below render `null`, and the home page closes
 * up around them as though they were never there.
 */
export function BrandStory() {
  const { about_sections: sections } = useStorefrontBrand();
  const copy = useStorefrontCopy();

  if (sections.length === 0) return null;

  return (
    <section className="brand-story">
      <div className="page-pad section-pad brand-story__inner">
        <p className="eyebrow">About us</p>
        <h2 className="font-display brand-story__title">{copy.name}</h2>

        <div className="brand-story__grid">
          {sections.map((section, index) => (
            <article className="brand-story__card rise-in" style={{ "--i": Math.min(index, 11) } as React.CSSProperties} key={`${section.heading}-${index}`}>
              <h3>{section.heading}</h3>
              {/* Split on blank lines rather than rendered as one block: the
                  owner's paragraph breaks are stored (`restaurant_brand.py`
                  keeps them deliberately, unlike the short copy) and throwing
                  them away here would make three paragraphs one wall. Never
                  dangerouslySetInnerHTML — this is somebody's typing. */}
              {section.body
                .split(/\n{2,}/)
                .map((paragraph) => paragraph.trim())
                .filter(Boolean)
                .map((paragraph, at) => (
                  <p key={at}>{paragraph}</p>
                ))}
              {section.bullets && section.bullets.length > 0 && (
                <ul>
                  {section.bullets.map((bullet, at) => (
                    <li key={at}>{bullet}</li>
                  ))}
                </ul>
              )}
            </article>
          ))}
        </div>
      </div>
    </section>
  );
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
        <h2 className="font-display brand-faqs__title">Questions people ask</h2>

        <div className="brand-faqs__list">
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
          __html: JSON.stringify({
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
