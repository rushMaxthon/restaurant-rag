import { Check } from 'lucide-react';

export interface WizardStep {
  id: number;
  label: string;
}

interface WizardStepsProps {
  steps: WizardStep[];
  current: number;
  /** Highest step reached, so a completed step can be clicked back to. */
  furthest: number;
  onSelect: (step: number) => void;
}

/**
 * The progress rail above the builder.
 *
 * Drawn as one connected path rather than five chips, because the point it has
 * to make is "you are three of five through a thing that ends" — the single
 * most reassuring thing a multi-step form can tell someone.
 *
 * Steps behind the current one are clickable and steps ahead are not: the
 * wizard validates forward, so jumping to "Schedule" from "Goal" would land on
 * a review screen describing an audience that was never chosen.
 */
export function WizardSteps({ steps, current, furthest, onSelect }: WizardStepsProps) {
  return (
    <ol aria-label="Campaign steps" className="mkt-steps">
      {steps.map((step) => {
        const isDone = step.id < current;
        const isCurrent = step.id === current;
        const reachable = step.id <= furthest;

        return (
          <li
            className={[
              'mkt-steps__item',
              isCurrent ? 'mkt-steps__item--current' : null,
              isDone ? 'mkt-steps__item--done' : null,
            ]
              .filter(Boolean)
              .join(' ')}
            key={step.id}
          >
            <button
              aria-current={isCurrent ? 'step' : undefined}
              className="mkt-steps__button"
              disabled={!reachable || isCurrent}
              onClick={() => onSelect(step.id)}
              type="button"
            >
              <span aria-hidden="true" className="mkt-steps__marker">
                {isDone ? <Check size={16} strokeWidth={3} /> : step.id}
              </span>
              <span className="mkt-steps__label">{step.label}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
