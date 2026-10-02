import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { AddressFields } from "@/lib/delivery-address";

/**
 * One labelled, validated address box.
 *
 * Declared at module scope on purpose. Defined inside the checkout it would
 * be a NEW component type on every render, so React would unmount and remount
 * the input on each keystroke — focus lost, and only the first character kept.
 * Everything it needs arrives as props instead.
 */
export function AddressField({
  id,
  label,
  placeholder,
  autoComplete,
  hint,
  className,
  icon,
  inputMode,
  value,
  problem,
  onChange,
  onBlur,
}: {
  id: keyof AddressFields;
  label: string;
  placeholder: string;
  autoComplete: string;
  hint?: string;
  className?: string;
  icon?: React.ReactNode;
  inputMode?: "text" | "numeric" | "tel";
  value: string;
  problem?: string | undefined;
  onChange: (next: string) => void;
  onBlur: () => void;
}) {
  return (
    <div className={`space-y-1.5 ${className ?? ""}`}>
      <Label htmlFor={id}>
        {label}
        {hint && <span className="ml-1.5 text-xs font-medium text-muted">{hint}</span>}
      </Label>
      <div className="field-wrap" data-invalid={Boolean(problem)}>
        {icon}
        <Input
          id={id}
          value={value}
          placeholder={placeholder}
          autoComplete={autoComplete}
          {...(inputMode ? { inputMode } : {})}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onBlur}
          aria-invalid={Boolean(problem)}
          aria-describedby={problem ? `${id}-error` : undefined}
          className="h-12"
        />
      </div>
      {problem && (
        <p className="field-error" id={`${id}-error`}>
          {problem}
        </p>
      )}
    </div>
  );
}
