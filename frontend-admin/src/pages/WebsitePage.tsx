/**
 * Everything a restaurant's own website says, in one place an owner can edit.
 *
 * The platform has been able to store this since `restaurant_storefront.py`
 * was written, and nothing in this panel could set it — those eight strings
 * were reachable only by a curl call, so in practice every tenant ran on the
 * defaults derived from their name and city. The brand content below them
 * (`restaurant_brand.py`, migration 0073) is new and has never had a screen.
 *
 * **Two saves, not one.** The short copy and the long-form content are
 * separate endpoints with separate validation, and an owner correcting a page
 * title should not have their FAQ re-submitted and re-validated to do it. Each
 * block saves itself and says so.
 *
 * **Only edited fields are sent.** The GET answers with every key filled in —
 * written values and derived defaults alike — so posting the form back whole
 * would turn all eight defaults into values the owner "wrote", and they would
 * stop tracking the restaurant's own details forever after. `changedCopy` is
 * what prevents that, and the reasoning is written out there.
 *
 * **Nothing in the brand block is invented.** Empty is the normal state and
 * the storefront renders nothing for it. The headings offered below are
 * placeholders, which prompt without publishing — a derived "Commitment to
 * Quality" paragraph would be our words under a real business's name, and the
 * same words under every tenant's.
 */

import { ArrowDown, ArrowUp, Globe, Plus, RotateCcw, Trash2, TriangleAlert } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { PageIntro } from '../components/PageIntro';
import { StatePanel } from '../components/StatePanel';
import {
  RestaurantScopePicker,
  RestaurantScopePrompt,
} from '../components/marketing/RestaurantScopePicker';
import { useMarketingScope } from '../hooks/useMarketingScope';
import { ApiError, api } from '../services/api';
import {
  COPY_GROUPS,
  EMPTY_FAQ,
  EMPTY_SECTION,
  FAQ_PROMPTS,
  SECTION_PROMPTS,
  changedCopy,
  faqProblem,
  moveRow,
  sectionProblem,
  usableFaqs,
  usableHighlights,
  usableSections,
  usableSpecialities,
  yearProblem,
  highlightProblem,
  EMPTY_HIGHLIGHT,
  SPECIALITY_PROMPTS,
} from '../services/websiteContent';
import type {
  BrandFaq,
  BrandHighlight,
  BrandSection,
  RestaurantBrand,
  RestaurantStorefront,
  StorefrontCopyKey,
  UserRole,
} from '../types/app';

interface WebsitePageProps {
  token: string;
  role: UserRole;
  /** The owner's own restaurant. Null for an admin, who chooses one. */
  restaurantId: string | null;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

type Copy = Record<StorefrontCopyKey, string>;

export function WebsitePage({ token, role, restaurantId, onToast }: WebsitePageProps) {
  const isAdmin = role === 'ADMIN';
  // The same hook every tenant-scoped screen uses. An admin with no restaurant
  // chosen gets `400 restaurant_id is required` on every call and a page that
  // reads as broken instead of as a question.
  const scope = useMarketingScope();
  const viewedRestaurantId = isAdmin ? scope.selectedRestaurantId : restaurantId;
  const ready = isAdmin ? scope.ready && Boolean(scope.selectedRestaurantId) : Boolean(restaurantId);

  const [storefront, setStorefront] = useState<RestaurantStorefront | null>(null);
  const [brand, setBrand] = useState<RestaurantBrand | null>(null);
  const [copyDraft, setCopyDraft] = useState<Copy | null>(null);
  const [sections, setSections] = useState<BrandSection[]>([]);
  const [faqs, setFaqs] = useState<BrandFaq[]>([]);
  // Held as a string, not a number: an input the owner is halfway through
  // clearing is "" and "199", neither of which is a year, and coercing on
  // every keystroke fights the person typing.
  const [established, setEstablished] = useState('');
  const [specialities, setSpecialities] = useState<string[]>([]);
  const [highlights, setHighlights] = useState<BrandHighlight[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [savingCopy, setSavingCopy] = useState(false);
  const [savingBrand, setSavingBrand] = useState(false);

  useEffect(() => {
    if (!ready || !viewedRestaurantId) return;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    Promise.all([
      api.getRestaurantStorefront(token, viewedRestaurantId),
      api.getRestaurantBrand(token, viewedRestaurantId),
    ])
      .then(([copyResponse, brandResponse]) => {
        if (cancelled) return;
        setStorefront(copyResponse);
        setCopyDraft({ ...copyResponse.storefront });
        setBrand(brandResponse);
        setSections(brandResponse.brand.about_sections.map((s) => ({ ...s, bullets: s.bullets ?? [] })));
        setFaqs(brandResponse.brand.faqs.map((f) => ({ ...f })));
        setEstablished(
          brandResponse.brand.established_year ? String(brandResponse.brand.established_year) : '',
        );
        setSpecialities([...brandResponse.brand.specialities]);
        setHighlights(brandResponse.brand.highlights.map((h) => ({ note: '', ...h })));
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoadError(
          error instanceof ApiError ? error.message : 'We could not load this website’s words.',
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ready, token, viewedRestaurantId]);

  const limits = brand?.limits ?? {};
  const maxSections = limits['max_sections'] ?? 8;
  const maxFaqs = limits['max_faqs'] ?? 12;

  const copyChanges = useMemo(
    () => (storefront && copyDraft ? changedCopy(storefront.storefront, copyDraft) : {}),
    [storefront, copyDraft],
  );
  const copyDirty = Object.keys(copyChanges).length > 0;

  const sectionProblems = sections.map((section) => sectionProblem(section, limits));
  const faqProblems = faqs.map((faq) => faqProblem(faq, limits));
  const highlightProblems = highlights.map((highlight) => highlightProblem(highlight, limits));
  const establishedProblem = yearProblem(established, limits);
  const brandBlocked = [
    ...sectionProblems,
    ...faqProblems,
    ...highlightProblems,
    establishedProblem,
  ].some(Boolean);
  const maxSpecialities = limits['max_specialities'] ?? 10;
  const maxHighlights = limits['max_highlights'] ?? 4;

  const saveCopy = useCallback(async () => {
    if (!viewedRestaurantId || !copyDirty) return;
    setSavingCopy(true);
    try {
      const saved = await api.updateRestaurantStorefront(token, viewedRestaurantId, copyChanges);
      setStorefront(saved);
      setCopyDraft({ ...saved.storefront });
      onToast('Saved', 'Your website’s words are updated.', 'success');
    } catch (error: unknown) {
      onToast(
        'Not saved',
        error instanceof ApiError ? error.message : 'Something went wrong. Try again.',
        'error',
      );
    } finally {
      setSavingCopy(false);
    }
  }, [copyChanges, copyDirty, onToast, token, viewedRestaurantId]);

  const saveBrand = useCallback(async () => {
    if (!viewedRestaurantId) return;
    setSavingBrand(true);
    try {
      const saved = await api.updateRestaurantBrand(token, viewedRestaurantId, {
        // Blank rows are dropped here as well as on the server, so what comes
        // back matches what the owner can see was worth keeping.
        about_sections: usableSections(sections),
        faqs: usableFaqs(faqs),
        // An empty box clears the year rather than leaving the old one, which
        // is the same contract the sections have: sending a key is an edit.
        established_year: established.trim() === '' ? null : Number(established.trim()),
        specialities: usableSpecialities(specialities),
        highlights: usableHighlights(highlights),
      });
      setBrand(saved);
      setSections(saved.brand.about_sections.map((s) => ({ ...s, bullets: s.bullets ?? [] })));
      setFaqs(saved.brand.faqs.map((f) => ({ ...f })));
      setEstablished(saved.brand.established_year ? String(saved.brand.established_year) : '');
      setSpecialities([...saved.brand.specialities]);
      setHighlights(saved.brand.highlights.map((h) => ({ note: '', ...h })));
      onToast('Saved', 'Your about page and questions are updated.', 'success');
    } catch (error: unknown) {
      onToast(
        'Not saved',
        error instanceof ApiError ? error.message : 'Something went wrong. Try again.',
        'error',
      );
    } finally {
      setSavingBrand(false);
    }
  }, [established, faqs, highlights, onToast, sections, specialities, token, viewedRestaurantId]);

  return (
    <div className="page">
      <PageIntro
        help="website"
        eyebrow="Manage"
        title="Storefront content"
        description="The words on your own site: what a search result shows, what the home page says, and what you tell somebody who has not ordered from you before."
      />

      {/* Renders nothing for an owner, who has one restaurant and may not name
          it — the backend refuses a `restaurant_id` from them. */}
      {isAdmin && ready && <RestaurantScopePicker scope={scope} />}

      {/* The purpose-built prompt rather than a generic panel: asking is the
          point, and this is the component that already says it the way the
          other tenant-scoped screens do. */}
      {isAdmin && !ready && <RestaurantScopePrompt scope={scope} what="These words" />}

      {ready && loadError && (
        <StatePanel
          icon={TriangleAlert}
          tone="error"
          title="That did not load"
          description={loadError}
        />
      )}

      {ready && loading && !storefront && (
        <StatePanel
          icon={Globe}
          title="Loading"
          description="Fetching this restaurant’s words."
        />
      )}

      {ready && storefront && copyDraft && (
        <section className="web-block">
          <header className="web-block__head">
            <div>
              <h2>The short words</h2>
              <p>
                Every one of these has a sensible default built from your name, cuisine and city.
                Leave a field untouched and it keeps tracking those details; write in it and it
                stays exactly as you wrote it. Clear it to go back.
              </p>
            </div>
            <button
              type="button"
              className="primary-button"
              disabled={!copyDirty || savingCopy}
              onClick={() => void saveCopy()}
            >
              {savingCopy ? 'Saving…' : copyDirty ? `Save ${Object.keys(copyChanges).length}` : 'Saved'}
            </button>
          </header>

          {COPY_GROUPS.map((group) => (
            <div className="web-group" key={group.title}>
              <h3>{group.title}</h3>
              <p className="web-group__blurb">{group.blurb}</p>
              <div className="form-grid">
                {group.fields.map((field) => {
                  const value = copyDraft[field.key] ?? '';
                  const limit = storefront.limits[field.key] ?? 0;
                  const written = storefront.customized.includes(field.key);
                  const over = limit > 0 && value.trim().length > limit;
                  return (
                    <div className="field web-field" key={field.key}>
                      <label htmlFor={`copy-${field.key}`}>
                        {field.label}
                        {/* Said plainly, because the difference decides what
                            clearing the box will do. */}
                        <span className={written ? 'web-tag web-tag--written' : 'web-tag'}>
                          {written ? 'yours' : 'automatic'}
                        </span>
                      </label>
                      {field.multiline ? (
                        <textarea
                          id={`copy-${field.key}`}
                          rows={3}
                          value={value}
                          onChange={(event) =>
                            setCopyDraft((draft) =>
                              draft ? { ...draft, [field.key]: event.target.value } : draft,
                            )
                          }
                        />
                      ) : (
                        <input
                          id={`copy-${field.key}`}
                          type="text"
                          value={value}
                          onChange={(event) =>
                            setCopyDraft((draft) =>
                              draft ? { ...draft, [field.key]: event.target.value } : draft,
                            )
                          }
                        />
                      )}
                      <div className="web-field__foot">
                        <span className="web-hint">{field.hint}</span>
                        {limit > 0 && (
                          <span className={over ? 'web-count web-count--over' : 'web-count'}>
                            {value.trim().length} / {limit}
                          </span>
                        )}
                      </div>
                      {written && (
                        <button
                          type="button"
                          className="web-revert"
                          onClick={() =>
                            setCopyDraft((draft) =>
                              draft ? { ...draft, [field.key]: '' } : draft,
                            )
                          }
                        >
                          <RotateCcw size={13} aria-hidden="true" />
                          Back to “{storefront.defaults[field.key]}”
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </section>
      )}

      {ready && brand && (
        <section className="web-block">
          <header className="web-block__head">
            <div>
              <h2>About your kitchen</h2>
              <p>
                Headed sections on your home page, and the questions people ask before a first
                order. Nothing here is written for you — what you leave empty simply does not
                appear.
              </p>
            </div>
            <button
              type="button"
              className="primary-button"
              disabled={savingBrand || brandBlocked}
              onClick={() => void saveBrand()}
            >
              {savingBrand ? 'Saving…' : 'Save'}
            </button>
          </header>

          <div className="web-group">
            <h3>The facts above the fold</h3>
            <p className="web-group__blurb">
              The first things a new customer reads on your home page. All three are optional, and
              anything you leave empty simply does not appear.
            </p>

            <div className="field">
              <label htmlFor="established">The year you opened</label>
              <input
                id="established"
                type="text"
                inputMode="numeric"
                maxLength={4}
                placeholder="1999"
                value={established}
                onChange={(event) => setEstablished(event.target.value)}
                aria-invalid={establishedProblem ? true : undefined}
              />
              <div className="web-field__foot">
                {/* The year, never "26 years in business" — that is right on
                    the day it is typed and wrong every year after. The site
                    counts up from this. */}
                <span className="web-hint">
                  Shown as &ldquo;Since 1999&rdquo;, with the years counted up for you.
                </span>
              </div>
              {establishedProblem && <p className="web-problem">{establishedProblem}</p>}
            </div>

            <div className="field">
              <label>What you are known for</label>
              <div className="web-field__foot">
                <span className="web-hint">
                  A few words each &mdash; what someone nearby would name if you asked them about
                  you.
                </span>
                <span className="web-count">
                  {specialities.length} / {maxSpecialities}
                </span>
              </div>
              {specialities.map((speciality, index) => (
                <div className="web-inline" key={`speciality-${index}`}>
                  <input
                    type="text"
                    placeholder={SPECIALITY_PROMPTS[index % SPECIALITY_PROMPTS.length]}
                    value={speciality}
                    aria-label={`Speciality ${index + 1}`}
                    onChange={(event) =>
                      setSpecialities((rows) =>
                        rows.map((row, at) => (at === index ? event.target.value : row)),
                      )
                    }
                  />
                  <button
                    type="button"
                    className="web-inline__remove"
                    aria-label={`Remove speciality ${index + 1}`}
                    onClick={() => setSpecialities((rows) => rows.filter((_, at) => at !== index))}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                </div>
              ))}
              {specialities.length < maxSpecialities && (
                <button
                  type="button"
                  className="web-add"
                  onClick={() => setSpecialities((rows) => [...rows, ''])}
                >
                  <Plus size={14} aria-hidden="true" /> Add one
                </button>
              )}
            </div>

            <div className="field">
              <label>Figures worth showing</label>
              <div className="web-field__foot">
                <span className="web-hint">
                  A figure and a caption. If it came from somewhere else &mdash; a rating on a
                  listing site &mdash; say where: a number with no source reads as ours.
                </span>
                <span className="web-count">
                  {highlights.length} / {maxHighlights}
                </span>
              </div>
              {highlights.map((highlight, index) => (
                <div className="web-inline web-inline--trio" key={`highlight-${index}`}>
                  <input
                    type="text"
                    placeholder="4.6"
                    value={highlight.value}
                    aria-label={`Figure ${index + 1}`}
                    onChange={(event) =>
                      setHighlights((rows) =>
                        rows.map((row, at) =>
                          at === index ? { ...row, value: event.target.value } : row,
                        ),
                      )
                    }
                  />
                  <input
                    type="text"
                    placeholder="Rated by customers"
                    value={highlight.label}
                    aria-label={`Caption ${index + 1}`}
                    onChange={(event) =>
                      setHighlights((rows) =>
                        rows.map((row, at) =>
                          at === index ? { ...row, label: event.target.value } : row,
                        ),
                      )
                    }
                  />
                  <input
                    type="text"
                    placeholder="85 reviews on JustDial"
                    value={highlight.note ?? ''}
                    aria-label={`Where figure ${index + 1} came from`}
                    onChange={(event) =>
                      setHighlights((rows) =>
                        rows.map((row, at) =>
                          at === index ? { ...row, note: event.target.value } : row,
                        ),
                      )
                    }
                  />
                  <button
                    type="button"
                    className="web-inline__remove"
                    aria-label={`Remove figure ${index + 1}`}
                    onClick={() => setHighlights((rows) => rows.filter((_, at) => at !== index))}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                </div>
              ))}
              {highlightProblems.map((problem, index) =>
                problem ? (
                  <p className="web-problem" key={`highlight-problem-${index}`}>
                    {problem}
                  </p>
                ) : null,
              )}
              {highlights.length < maxHighlights && (
                <button
                  type="button"
                  className="web-add"
                  onClick={() => setHighlights((rows) => [...rows, { ...EMPTY_HIGHLIGHT }])}
                >
                  <Plus size={14} aria-hidden="true" /> Add one
                </button>
              )}
            </div>
          </div>

          <div className="web-group">
            <h3>Sections</h3>
            <p className="web-group__blurb">
              Shown on the home page in this order. {sections.length} of {maxSections} used.
            </p>

            {sections.map((section, index) => (
              <div className="web-row" key={`section-${index}`}>
                <div className="web-row__bar">
                  <span className="web-row__n">{index + 1}</span>
                  <div className="web-row__tools">
                    <button
                      type="button"
                      aria-label="Move up"
                      disabled={index === 0}
                      onClick={() => setSections((rows) => moveRow(rows, index, -1))}
                    >
                      <ArrowUp size={14} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      aria-label="Move down"
                      disabled={index === sections.length - 1}
                      onClick={() => setSections((rows) => moveRow(rows, index, 1))}
                    >
                      <ArrowDown size={14} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      aria-label="Remove section"
                      className="web-row__remove"
                      onClick={() => setSections((rows) => rows.filter((_, at) => at !== index))}
                    >
                      <Trash2 size={14} aria-hidden="true" />
                    </button>
                  </div>
                </div>
                <div className="field">
                  <label htmlFor={`section-heading-${index}`}>Heading</label>
                  <input
                    id={`section-heading-${index}`}
                    type="text"
                    value={section.heading}
                    placeholder={SECTION_PROMPTS[index % SECTION_PROMPTS.length]}
                    onChange={(event) =>
                      setSections((rows) =>
                        rows.map((row, at) =>
                          at === index ? { ...row, heading: event.target.value } : row,
                        ),
                      )
                    }
                  />
                </div>
                <div className="field">
                  <label htmlFor={`section-body-${index}`}>Words</label>
                  <textarea
                    id={`section-body-${index}`}
                    rows={4}
                    value={section.body}
                    onChange={(event) =>
                      setSections((rows) =>
                        rows.map((row, at) =>
                          at === index ? { ...row, body: event.target.value } : row,
                        ),
                      )
                    }
                  />
                  <div className="web-field__foot">
                    <span className="web-hint">Paragraph breaks are kept.</span>
                    <span className="web-count">
                      {section.body.trim().length} / {limits['body'] ?? 1200}
                    </span>
                  </div>
                </div>
                <div className="field">
                  <label htmlFor={`section-bullets-${index}`}>Bullet points</label>
                  {/* One per line rather than a repeater of repeaters: the
                      nesting is the only thing that would make this editor
                      hard to use, and a textarea is how everybody already
                      expects to type a short list. */}
                  <textarea
                    id={`section-bullets-${index}`}
                    rows={3}
                    value={(section.bullets ?? []).join('\n')}
                    placeholder={'One per line\nLeave empty for none'}
                    onChange={(event) =>
                      setSections((rows) =>
                        rows.map((row, at) =>
                          at === index
                            ? { ...row, bullets: event.target.value.split('\n') }
                            : row,
                        ),
                      )
                    }
                  />
                </div>
                {sectionProblems[index] && (
                  <p className="web-problem">{sectionProblems[index]}</p>
                )}
              </div>
            ))}

            <button
              type="button"
              className="secondary-button web-add"
              disabled={sections.length >= maxSections}
              onClick={() => setSections((rows) => [...rows, { ...EMPTY_SECTION, bullets: [] }])}
            >
              <Plus size={14} aria-hidden="true" />
              Add a section
            </button>
          </div>

          <div className="web-group">
            <h3>Questions people ask</h3>
            <p className="web-group__blurb">
              Shown on your home page and offered to search engines as a FAQ. {faqs.length} of{' '}
              {maxFaqs} used.
            </p>

            {faqs.map((faq, index) => (
              <div className="web-row" key={`faq-${index}`}>
                <div className="web-row__bar">
                  <span className="web-row__n">{index + 1}</span>
                  <div className="web-row__tools">
                    <button
                      type="button"
                      aria-label="Move up"
                      disabled={index === 0}
                      onClick={() => setFaqs((rows) => moveRow(rows, index, -1))}
                    >
                      <ArrowUp size={14} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      aria-label="Move down"
                      disabled={index === faqs.length - 1}
                      onClick={() => setFaqs((rows) => moveRow(rows, index, 1))}
                    >
                      <ArrowDown size={14} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      aria-label="Remove question"
                      className="web-row__remove"
                      onClick={() => setFaqs((rows) => rows.filter((_, at) => at !== index))}
                    >
                      <Trash2 size={14} aria-hidden="true" />
                    </button>
                  </div>
                </div>
                <div className="field">
                  <label htmlFor={`faq-q-${index}`}>Question</label>
                  <input
                    id={`faq-q-${index}`}
                    type="text"
                    value={faq.question}
                    placeholder={FAQ_PROMPTS[index % FAQ_PROMPTS.length]}
                    onChange={(event) =>
                      setFaqs((rows) =>
                        rows.map((row, at) =>
                          at === index ? { ...row, question: event.target.value } : row,
                        ),
                      )
                    }
                  />
                </div>
                <div className="field">
                  <label htmlFor={`faq-a-${index}`}>Answer</label>
                  <textarea
                    id={`faq-a-${index}`}
                    rows={3}
                    value={faq.answer}
                    onChange={(event) =>
                      setFaqs((rows) =>
                        rows.map((row, at) =>
                          at === index ? { ...row, answer: event.target.value } : row,
                        ),
                      )
                    }
                  />
                </div>
                {faqProblems[index] && <p className="web-problem">{faqProblems[index]}</p>}
              </div>
            ))}

            <button
              type="button"
              className="secondary-button web-add"
              disabled={faqs.length >= maxFaqs}
              onClick={() => setFaqs((rows) => [...rows, { ...EMPTY_FAQ }])}
            >
              <Plus size={14} aria-hidden="true" />
              Add a question
            </button>
          </div>

          {brandBlocked && (
            <p className="web-problem web-problem--foot">
              <Globe size={14} aria-hidden="true" />
              Fix the rows marked above, or clear them, before saving.
            </p>
          )}
        </section>
      )}
    </div>
  );
}
