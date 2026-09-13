import { useId, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { Input } from "@/components/ui/input";

type PasswordInputProps = {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: "current-password" | "new-password";
  placeholder?: string;
  minLength?: number;
  required?: boolean;
};

/**
 * A password field the visitor can actually read back.
 *
 * Typing a password blind is the single easiest place to fail a sign-up, and
 * the usual fix is a reveal toggle. The button is deliberately a `button` with
 * an aria-label rather than a bare icon: without type="button" it submits the
 * form, and screen readers otherwise announce nothing at all.
 */
export function PasswordInput({
  id,
  value,
  onChange,
  autoComplete,
  placeholder = "••••••••",
  minLength,
  required = true,
}: PasswordInputProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const [visible, setVisible] = useState(false);

  return (
    <div className="relative">
      <Input
        id={inputId}
        type={visible ? "text" : "password"}
        required={required}
        minLength={minLength}
        autoComplete={autoComplete}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="h-12 pr-12"
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? "Hide password" : "Show password"}
        aria-pressed={visible}
        className="pw-toggle absolute inset-y-0 right-0 flex w-12 items-center justify-center text-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {visible ? <EyeOff className="size-5" /> : <Eye className="size-5" />}
      </button>
    </div>
  );
}
