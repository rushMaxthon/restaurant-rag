import { CheckCircle2 } from "lucide-react";

/** Cart → Checkout → Confirmation, rendered as a rail rather than a text label. */
export function StepRail({ step }: { step: 1 | 2 | 3 }) {
  const steps = ["Cart", "Checkout", "Confirmation"] as const;
  return (
    // Sized to fit three steps on one line at 414px. It wrapped before, and
    // wrapping put "Confirmation" alone on a second row with the connector
    // that should have led to it left dangling off the end of the first —
    // a rail pointing at nothing. The connector now comes BEFORE each step
    // rather than after, so if it ever does wrap the line leads into the step
    // it belongs to instead of trailing into empty space.
    <ol className="flex flex-wrap items-center gap-x-2 gap-y-2 text-xs font-bold sm:gap-x-3 sm:text-sm">
      {steps.map((label, i) => {
        const index = (i + 1) as 1 | 2 | 3;
        const done = index < step;
        const todo = index > step;
        return (
          <li className="flex items-center gap-2 sm:gap-3" key={label}>
            {index > 1 && <span className="h-px w-4 bg-border sm:w-10" aria-hidden="true" />}
            <span className="flex items-center gap-1.5 sm:gap-2">
              <span className="step-pill" data-done={done} data-todo={todo}>
                {done ? <CheckCircle2 className="size-4" /> : index}
              </span>
              <span className={todo ? "text-muted" : undefined}>{label}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
