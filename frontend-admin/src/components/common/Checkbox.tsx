import { Check } from "lucide-react";
import type { ReactNode } from "react";

type CheckboxSize = "sm" | "md";
type CheckboxVariant = "default" | "ghost";

interface CheckboxProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: ReactNode;
  disabled?: boolean;
  size?: CheckboxSize;
  variant?: CheckboxVariant;
  className?: string;
}

function getCheckboxClassName({
  checked,
  disabled,
  size,
  variant,
  className,
}: {
  checked: boolean;
  disabled: boolean;
  size: CheckboxSize;
  variant: CheckboxVariant;
  className?: string;
}): string {
  return [
    "ui-checkbox",
    `ui-checkbox--${size}`,
    `ui-checkbox--${variant}`,
    checked ? "ui-checkbox--checked" : null,
    disabled ? "ui-checkbox--disabled" : null,
    className ?? null,
  ]
    .filter(Boolean)
    .join(" ");
}

export function Checkbox({
  checked,
  onChange,
  label,
  disabled = false,
  size = "md",
  variant = "default",
  className,
}: CheckboxProps) {
  return (
    <button
      aria-checked={checked}
      aria-disabled={disabled || undefined}
      className={getCheckboxClassName({
        checked,
        disabled,
        size,
        variant,
        className,
      })}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      role="checkbox"
      type="button"
    >
      <span aria-hidden="true" className="ui-checkbox__control">
        <Check size={size === "sm" ? 11 : 13} strokeWidth={3} />
      </span>
      <span className="ui-checkbox__label">{label}</span>
    </button>
  );
}
