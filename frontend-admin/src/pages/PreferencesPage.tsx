/**
 * Managing the onboarding questionnaire.
 *
 * What an admin sees depends on who they are, and the page says so rather than
 * silently disabling controls:
 *
 * * A **platform admin** edits the global questions every restaurant inherits.
 * * An **owner** sees those as read-only with one control that is theirs — hide
 *   it for this restaurant — plus full control over questions they author.
 *
 * Reordering uses explicit up/down controls rather than drag-and-drop: the list
 * is short, the target is a row rather than a pixel, and it behaves the same on
 * a laptop and on a tablet in a kitchen office.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Circle,
  Eye,
  EyeOff,
  Layers,
  ListChecks,
  Lock,
  MessageSquareText,
  Pencil,
  Plus,
  Trash2,
  Users,
} from 'lucide-react';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { ErrorPanel } from '../components/ErrorPanel';
import { Modal } from '../components/Modal';
import { PageIntro } from '../components/PageIntro';
import { StatTiles, type StatTileItem } from '../components/StatTiles';
import { ApiError, api } from '../services/api';
import type {
  AdminPreferenceQuestion,
  PreferenceInputType,
  PreferenceOptionDraft,
  PreferenceQuestionDraft,
  PreferenceSignalRole,
  UserRole,
} from '../types/app';

interface PreferencesPageProps {
  token: string;
  role: UserRole;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

/** Each role, in the admin's language rather than the code's. */
const ROLE_LABELS: Record<PreferenceSignalRole, string> = {
  CUISINE: 'Cuisine matching',
  DISLIKED_CUISINE: 'Excludes a cuisine',
  DIET: 'Dietary matching',
  SPICE: 'Spice matching',
  BUDGET: 'Budget matching',
  FAVORITE_ITEM: 'Favourite-dish matching',
  NONE: 'Collected only',
};

const ROLE_HELP: Record<PreferenceSignalRole, string> = {
  CUISINE: 'Answers push matching cuisines up the customer’s feed.',
  DISLIKED_CUISINE: 'Answers push a cuisine down the feed, or out of it.',
  DIET: 'Answers decide whether veg or non-veg dishes rank higher.',
  SPICE: 'Answers bias the feed toward milder or hotter dishes.',
  BUDGET: 'Answers keep suggested prices near what they usually spend.',
  FAVORITE_ITEM: 'Answers boost the dishes they named, and things like them.',
  NONE: 'Stored against the customer, but nothing in their feed changes.',
};

const ROLE_ORDER: PreferenceSignalRole[] = [
  'NONE',
  'CUISINE',
  'DIET',
  'SPICE',
  'BUDGET',
  'FAVORITE_ITEM',
  'DISLIKED_CUISINE',
];

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 64);
}

function emptyDraft(): PreferenceQuestionDraft {
  return {
    key: '',
    prompt: '',
    help_text: '',
    input_type: 'MULTI_SELECT',
    is_required: false,
    min_selections: 0,
    max_selections: null,
    allows_free_text: false,
    signal_role: 'NONE',
    is_active: true,
    options: [],
  };
}

/**
 * A checkbox that looks like the rest of the panel.
 *
 * The native control was the worst thing in the old form: a 13px square with
 * the label floating beside it, at odds with every other input on the page.
 * This makes the whole row the target and gives each switch room to explain
 * what it does.
 */
function ToggleRow({
  checked,
  onChange,
  title,
  description,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  title: string;
  description: string;
}) {
  return (
    <button
      aria-pressed={checked}
      className={checked ? 'pref-toggle pref-toggle--on' : 'pref-toggle'}
      onClick={() => onChange(!checked)}
      type="button"
    >
      <span className="pref-toggle__mark">
        {checked ? (
          <CheckCircle2 size={18} strokeWidth={2.2} />
        ) : (
          <Circle size={18} strokeWidth={2} />
        )}
      </span>
      <span className="pref-toggle__copy">
        <strong>{title}</strong>
        <small>{description}</small>
      </span>
    </button>
  );
}

export function PreferencesPage({ token, role, onToast }: PreferencesPageProps) {
  const isPlatformAdmin = role === 'ADMIN';

  const [questions, setQuestions] = useState<AdminPreferenceQuestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [editing, setEditing] = useState<AdminPreferenceQuestion | null>(null);
  const [draft, setDraft] = useState<PreferenceQuestionDraft | null>(null);
  const [optionRows, setOptionRows] = useState<PreferenceOptionDraft[]>([]);
  const [saving, setSaving] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<AdminPreferenceQuestion | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setQuestions(await api.getPreferenceQuestions(token));
      setError(null);
    } catch (nextError) {
      setError(
        nextError instanceof ApiError
          ? nextError.message
          : 'Unable to load preference questions.',
      );
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const ordered = useMemo(
    () => [...questions].sort((a, b) => a.display_order - b.display_order),
    [questions],
  );

  const tiles = useMemo<StatTileItem[]>(() => {
    const hidden = ordered.filter(
      (question) => question.is_hidden_here || !question.is_active,
    ).length;
    return [
      {
        key: 'asked',
        label: 'Asked in the app',
        icon: MessageSquareText,
        value: ordered.length - hidden,
        hint: 'What a new customer sees',
        isStatic: true,
      },
      { key: 'hidden', label: 'Hidden', icon: EyeOff, value: hidden, isStatic: true },
      {
        key: 'ranking',
        label: 'Feeding recommendations',
        icon: Layers,
        value: ordered.filter((question) => question.signal_role !== 'NONE').length,
        isStatic: true,
      },
      {
        key: 'answers',
        label: 'Saved answers',
        icon: Users,
        value: ordered.reduce((total, question) => total + question.answer_count, 0),
        isStatic: true,
      },
    ];
  }, [ordered]);

  const canEdit = (question: AdminPreferenceQuestion) =>
    isPlatformAdmin ? !question.restaurant_id : Boolean(question.restaurant_id);

  // --- actions -----------------------------------------------------------

  const run = async (id: string, action: () => Promise<unknown>, success: string) => {
    setBusyId(id);
    try {
      await action();
      await load();
      onToast('Saved', success, 'success');
    } catch (nextError) {
      onToast(
        'Not saved',
        nextError instanceof ApiError ? nextError.message : 'Something went wrong.',
        'error',
      );
    } finally {
      setBusyId(null);
    }
  };

  const move = (question: AdminPreferenceQuestion, delta: -1 | 1) => {
    const index = ordered.findIndex((entry) => entry.id === question.id);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= ordered.length) {
      return;
    }
    const next = [...ordered];
    [next[index], next[target]] = [next[target], next[index]];
    void run(
      question.id,
      () => api.reorderPreferenceQuestions(token, next.map((entry) => entry.id)),
      'Question order updated.',
    );
  };

  const openEditor = (question: AdminPreferenceQuestion | null) => {
    setEditing(question);
    if (question) {
      setDraft({
        key: question.key,
        prompt: question.prompt,
        help_text: question.help_text ?? '',
        input_type: question.input_type,
        is_required: question.is_required,
        min_selections: question.min_selections,
        max_selections: question.max_selections,
        allows_free_text: question.allows_free_text,
        signal_role: question.signal_role,
        is_active: question.is_active,
        options: [],
      });
      setOptionRows(
        question.options.map((option) => ({
          value: option.value,
          label: option.label,
          is_active: option.is_active,
        })),
      );
    } else {
      setDraft(emptyDraft());
      setOptionRows([{ value: '', label: '' }]);
    }
  };

  const closeEditor = () => {
    if (saving) {
      return;
    }
    setEditing(null);
    setDraft(null);
    setOptionRows([]);
  };

  const moveOption = (index: number, delta: -1 | 1) => {
    const target = index + delta;
    if (target < 0 || target >= optionRows.length) {
      return;
    }
    const next = [...optionRows];
    [next[index], next[target]] = [next[target], next[index]];
    setOptionRows(next);
  };

  const saveDraft = async () => {
    if (!draft) {
      return;
    }
    const cleanedOptions = optionRows
      .map((option) => ({
        ...option,
        label: option.label.trim(),
        value: (option.value || slugify(option.label)).trim(),
      }))
      .filter((option) => option.label && option.value);

    if (!draft.prompt.trim()) {
      onToast('Add a question', 'A question needs something to ask.', 'error');
      return;
    }
    if (cleanedOptions.length === 0 && !draft.allows_free_text) {
      onToast(
        'Add at least one option',
        'A question with no options and no free text gives the customer nothing to answer.',
        'error',
      );
      return;
    }

    setSaving(true);
    try {
      if (editing) {
        await api.updatePreferenceQuestion(token, editing.id, {
          prompt: draft.prompt.trim(),
          help_text: draft.help_text?.trim() || null,
          input_type: draft.input_type,
          is_required: draft.is_required,
          min_selections: draft.min_selections,
          max_selections: draft.max_selections,
          allows_free_text: draft.allows_free_text,
          signal_role: draft.signal_role,
          is_active: draft.is_active,
        });
        // Only additions are created here. Existing options keep their ids, so a
        // customer's stored answer is never orphaned by an edit.
        const existing = new Set(editing.options.map((option) => option.value));
        for (const option of cleanedOptions) {
          if (!existing.has(option.value)) {
            await api.createPreferenceOption(token, editing.id, option);
          }
        }
      } else {
        await api.createPreferenceQuestion(token, {
          ...draft,
          key: draft.key.trim() || slugify(draft.prompt),
          prompt: draft.prompt.trim(),
          help_text: draft.help_text?.trim() || null,
          options: cleanedOptions,
        });
      }
      await load();
      onToast('Saved', editing ? 'Question updated.' : 'Question added.', 'success');
      setEditing(null);
      setDraft(null);
      setOptionRows([]);
    } catch (nextError) {
      onToast(
        'Not saved',
        nextError instanceof ApiError ? nextError.message : 'Something went wrong.',
        'error',
      );
    } finally {
      setSaving(false);
    }
  };

  // --- render ------------------------------------------------------------

  const intro = (
    <PageIntro
      eyebrow="Preferences"
      title="Onboarding questions"
      description={
        isPlatformAdmin
          ? 'Asked in every restaurant’s app unless an owner hides one for themselves. Changes reach customers immediately — no app release.'
          : 'What your customers answer when they first open your app. Platform questions can be hidden but not edited. Changes reach customers immediately.'
      }
      actions={
        <button className="primary-button" onClick={() => openEditor(null)} type="button">
          <Plus size={16} strokeWidth={2.2} />
          New question
        </button>
      }
    />
  );

  if (error) {
    return (
      <div className="page-stack">
        {intro}
        <ErrorPanel
          description={error}
          onRetry={() => void load()}
          title="Preference questions"
        />
      </div>
    );
  }

  return (
    <div className="page-stack">
      {intro}

      <StatTiles ariaLabel="Questionnaire summary" loading={loading} tiles={tiles} />

      {loading ? (
        <div className="pref-list">
          {[0, 1, 2].map((index) => (
            <div className="pref-row pref-row--skeleton" key={index} />
          ))}
        </div>
      ) : ordered.length === 0 ? (
        <div className="empty-panel">
          <ListChecks size={22} />
          <strong>No questions yet</strong>
          <span>Add one and it appears in the app immediately.</span>
        </div>
      ) : (
        <div className="pref-list">
          {ordered.map((question, index) => {
            const editable = canEdit(question);
            const hidden = question.is_hidden_here || !question.is_active;
            const busy = busyId === question.id;

            return (
              <article
                className={hidden ? 'pref-row pref-row--hidden' : 'pref-row'}
                key={question.id}
              >
                <div className="pref-row__rank">
                  <button
                    aria-label={`Move “${question.prompt}” earlier`}
                    disabled={index === 0 || busy}
                    onClick={() => move(question, -1)}
                    type="button"
                  >
                    <ArrowUp size={13} strokeWidth={2.6} />
                  </button>
                  <span className="pref-row__step">{index + 1}</span>
                  <button
                    aria-label={`Move “${question.prompt}” later`}
                    disabled={index === ordered.length - 1 || busy}
                    onClick={() => move(question, 1)}
                    type="button"
                  >
                    <ArrowDown size={13} strokeWidth={2.6} />
                  </button>
                </div>

                <div className="pref-row__main">
                  <div className="pref-row__title">
                    <h3>{question.prompt}</h3>
                    {/* Ownership only tells an owner something: on the platform
                        console every question is the platform's, so the badge
                        would repeat on every row and mean nothing. */}
                    {isPlatformAdmin ? null : question.is_inherited ? (
                      <span className="pref-tag">
                        <Lock size={11} strokeWidth={2.6} />
                        Platform
                      </span>
                    ) : (
                      <span className="pref-tag pref-tag--own">Yours</span>
                    )}
                    {hidden ? <span className="pref-tag pref-tag--off">Hidden</span> : null}
                  </div>

                  {question.help_text ? (
                    <p className="pref-row__help">{question.help_text}</p>
                  ) : null}

                  <ul className="pref-row__facts">
                    <li>
                      {question.input_type === 'SINGLE_SELECT' ? 'Pick one' : 'Pick several'}
                      {question.max_selections != null ? `, max ${question.max_selections}` : ''}
                    </li>
                    <li>{question.is_required ? 'Required' : 'Optional'}</li>
                    {question.allows_free_text ? <li>Free text</li> : null}
                    <li
                      className={
                        question.signal_role === 'NONE'
                          ? 'pref-row__fact--muted'
                          : 'pref-row__fact--signal'
                      }
                    >
                      {ROLE_LABELS[question.signal_role]}
                    </li>
                  </ul>

                  <div className="pref-row__options">
                    {question.options.slice(0, 7).map((option) => (
                      <span
                        className={option.is_active ? 'pref-chip' : 'pref-chip pref-chip--off'}
                        key={option.id}
                      >
                        {option.label}
                      </span>
                    ))}
                    {question.options.length > 7 ? (
                      <span className="pref-chip pref-chip--count">
                        +{question.options.length - 7}
                      </span>
                    ) : null}
                    {question.options.length === 0 ? (
                      <span className="pref-chip pref-chip--off">Free text only</span>
                    ) : null}
                  </div>

                  {question.answer_count > 0 ? (
                    <p className="pref-row__answers">
                      <Users size={12} strokeWidth={2.2} />
                      {question.answer_count} saved{' '}
                      {question.answer_count === 1 ? 'answer' : 'answers'} — retiring this keeps
                      them
                    </p>
                  ) : null}
                </div>

                <div className="pref-row__actions">
                  {editable ? (
                    <button
                      className="secondary-button"
                      disabled={busy}
                      onClick={() => openEditor(question)}
                      type="button"
                    >
                      <Pencil size={14} strokeWidth={2.2} />
                      Edit
                    </button>
                  ) : null}

                  {question.is_inherited ? (
                    <button
                      className="secondary-button"
                      disabled={busy}
                      onClick={() =>
                        void run(
                          question.id,
                          () =>
                            api.setPreferenceQuestionVisibility(
                              token,
                              question.id,
                              !question.is_hidden_here,
                            ),
                          question.is_hidden_here
                            ? 'Question shown again for your restaurant.'
                            : 'Question hidden for your restaurant only.',
                        )
                      }
                      type="button"
                    >
                      {question.is_hidden_here ? (
                        <>
                          <Eye size={14} strokeWidth={2.2} />
                          Show
                        </>
                      ) : (
                        <>
                          <EyeOff size={14} strokeWidth={2.2} />
                          Hide
                        </>
                      )}
                    </button>
                  ) : (
                    <button
                      className="secondary-button"
                      disabled={busy}
                      onClick={() =>
                        void run(
                          question.id,
                          () =>
                            api.updatePreferenceQuestion(token, question.id, {
                              is_active: !question.is_active,
                            }),
                          question.is_active ? 'Question disabled.' : 'Question enabled.',
                        )
                      }
                      type="button"
                    >
                      {question.is_active ? (
                        <>
                          <EyeOff size={14} strokeWidth={2.2} />
                          Disable
                        </>
                      ) : (
                        <>
                          <Eye size={14} strokeWidth={2.2} />
                          Enable
                        </>
                      )}
                    </button>
                  )}

                  {editable ? (
                    <button
                      aria-label={`Retire “${question.prompt}”`}
                      className="secondary-button pref-row__retire"
                      disabled={busy}
                      onClick={() => setPendingDelete(question)}
                      type="button"
                    >
                      <Trash2 size={14} strokeWidth={2.2} />
                    </button>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {draft ? (
        <Modal
          busy={saving}
          className="modal-card--compact"
          labelledBy="pref-editor-title"
          onClose={closeEditor}
        >
          {/* The three regions `.modal-card` expects. Putting everything in one
              div is what made the old editor clip its own title and push the
              save button off the bottom of the screen. */}
          <div className="panel__header modal-card__header">
            <div>
              <span className="eyebrow">{editing ? 'Question editor' : 'New question'}</span>
              <h2 id="pref-editor-title">
                {editing ? editing.prompt : 'Add an onboarding question'}
              </h2>
              <p className="hint-text">
                {editing
                  ? 'Changes reach the app as soon as you save.'
                  : 'It appears in every customer’s onboarding as soon as you save.'}
              </p>
            </div>
            <button
              aria-label="Close question editor"
              className="modal-close"
              disabled={saving}
              onClick={closeEditor}
              type="button"
            >
              ×
            </button>
          </div>

          <div className="modal-card__body pref-editor">
            <section className="pref-editor__section">
              <label className="field">
                <span>Question</span>
                <input
                  autoFocus
                  onChange={(event) => setDraft({ ...draft, prompt: event.target.value })}
                  placeholder="How spicy do you like it?"
                  value={draft.prompt}
                />
              </label>

              <label className="field">
                <span>Helper text</span>
                <input
                  onChange={(event) => setDraft({ ...draft, help_text: event.target.value })}
                  placeholder="One line under the question — optional"
                  value={draft.help_text ?? ''}
                />
              </label>
            </section>

            <section className="pref-editor__section">
              <h4 className="pref-editor__legend">How customers answer</h4>
              <div className="pref-editor__pair">
                <label className="field">
                  <span>Answer type</span>
                  <select
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        input_type: event.target.value as PreferenceInputType,
                      })
                    }
                    value={draft.input_type}
                  >
                    <option value="SINGLE_SELECT">Pick one</option>
                    <option value="MULTI_SELECT">Pick several</option>
                  </select>
                </label>

                <label className="field">
                  <span>Most they can pick</span>
                  <input
                    // Meaningless on a single-select, so it says so rather than
                    // accepting a number the server would ignore.
                    disabled={draft.input_type === 'SINGLE_SELECT'}
                    min={1}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        max_selections: event.target.value ? Number(event.target.value) : null,
                      })
                    }
                    placeholder={draft.input_type === 'SINGLE_SELECT' ? 'One' : 'No limit'}
                    type="number"
                    value={
                      draft.input_type === 'SINGLE_SELECT' ? '' : (draft.max_selections ?? '')
                    }
                  />
                </label>
              </div>

              <div className="pref-editor__toggles">
                <ToggleRow
                  checked={draft.is_required}
                  description="They cannot move past this question without answering."
                  onChange={(next) => setDraft({ ...draft, is_required: next })}
                  title="Required"
                />
                <ToggleRow
                  checked={draft.allows_free_text}
                  description="A text box beside the options, for anything you have not listed."
                  onChange={(next) => setDraft({ ...draft, allows_free_text: next })}
                  title="Let them type their own"
                />
              </div>
            </section>

            <section className="pref-editor__section">
              <h4 className="pref-editor__legend">Effect on recommendations</h4>
              <label className="field">
                <span>What this answer does</span>
                <select
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      signal_role: event.target.value as PreferenceSignalRole,
                    })
                  }
                  value={draft.signal_role}
                >
                  {ROLE_ORDER.map((value) => (
                    <option key={value} value={value}>
                      {ROLE_LABELS[value]}
                    </option>
                  ))}
                </select>
              </label>
              <p className="pref-editor__note">{ROLE_HELP[draft.signal_role]}</p>
            </section>

            <section className="pref-editor__section">
              <div className="pref-editor__legend-row">
                <h4 className="pref-editor__legend">
                  Options
                  <span className="pref-editor__count">{optionRows.length}</span>
                </h4>
                <button
                  className="secondary-button"
                  onClick={() => setOptionRows([...optionRows, { value: '', label: '' }])}
                  type="button"
                >
                  <Plus size={14} strokeWidth={2.2} />
                  Add option
                </button>
              </div>

              {optionRows.length === 0 ? (
                <p className="pref-editor__note">
                  No options yet. Customers can only answer if “let them type their own” is on.
                </p>
              ) : (
                <ol className="pref-editor__options">
                  {optionRows.map((option, index) => (
                    <li className="pref-editor__option" key={index}>
                      <span className="pref-editor__option-index">{index + 1}</span>
                      <input
                        onChange={(event) => {
                          const next = [...optionRows];
                          next[index] = { ...option, label: event.target.value };
                          setOptionRows(next);
                        }}
                        placeholder="What the customer sees"
                        value={option.label}
                      />
                      <div className="pref-editor__option-controls">
                        <button
                          aria-label={`Move option ${index + 1} up`}
                          disabled={index === 0}
                          onClick={() => moveOption(index, -1)}
                          type="button"
                        >
                          <ArrowUp size={13} strokeWidth={2.6} />
                        </button>
                        <button
                          aria-label={`Move option ${index + 1} down`}
                          disabled={index === optionRows.length - 1}
                          onClick={() => moveOption(index, 1)}
                          type="button"
                        >
                          <ArrowDown size={13} strokeWidth={2.6} />
                        </button>
                        <button
                          aria-label={`Remove option ${index + 1}`}
                          className="pref-editor__option-remove"
                          onClick={() =>
                            setOptionRows(optionRows.filter((_, position) => position !== index))
                          }
                          type="button"
                        >
                          <Trash2 size={13} strokeWidth={2.2} />
                        </button>
                      </div>
                    </li>
                  ))}
                </ol>
              )}

              {editing ? (
                <p className="pref-editor__note">
                  Removing an option here only stops it being offered. Customers who already
                  chose it keep their answer.
                </p>
              ) : null}
            </section>
          </div>

          <div className="modal-actions pref-editor__actions">
            <button
              className="secondary-button"
              disabled={saving}
              onClick={closeEditor}
              type="button"
            >
              Cancel
            </button>
            <button
              className="primary-button"
              disabled={saving}
              onClick={() => void saveDraft()}
              type="button"
            >
              {saving ? 'Saving…' : editing ? 'Save changes' : 'Add question'}
            </button>
          </div>
        </Modal>
      ) : null}

      <ConfirmDialog
        confirmLabel="Retire question"
        description={
          pendingDelete
            ? pendingDelete.answer_count > 0
              ? `${pendingDelete.answer_count} customers have answered this. Retiring it stops the question being asked — their answers are kept and nothing is deleted.`
              : 'This stops the question being asked. You can add it again later.'
            : ''
        }
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => {
          const target = pendingDelete;
          setPendingDelete(null);
          if (target) {
            void run(
              target.id,
              () => api.deletePreferenceQuestion(token, target.id),
              'Question retired.',
            );
          }
        }}
        open={Boolean(pendingDelete)}
        title={`Retire “${pendingDelete?.prompt ?? ''}”?`}
        tone="danger"
      />
    </div>
  );
}
