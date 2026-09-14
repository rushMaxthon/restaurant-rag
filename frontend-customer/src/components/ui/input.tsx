import * as React from "react";

import { cn } from "@/lib/utils";

/** Layout effect on the client, no-op on the server. See lib/auth.tsx. */
const useIsomorphicLayoutEffect =
  typeof window === "undefined" ? React.useEffect : React.useLayoutEffect;

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => {
    const innerRef = React.useRef<HTMLInputElement>(null);
    React.useImperativeHandle(ref, () => innerRef.current as HTMLInputElement, []);

    // Adopt anything already in the field when React attaches to it.
    //
    // The page is server-rendered, so the input exists and accepts keystrokes
    // before React has hydrated. This is a controlled input, so at hydration
    // React asserts its own state over the DOM — and that state is the empty
    // string, which silently throws away whatever was typed. It also discards
    // a password manager's autofill, which lands well before hydration.
    //
    // Measured on the login form: typing immediately after the field appeared
    // lost the whole value on one run in four, and the first character on
    // another. Replaying the DOM's value through onChange makes React adopt it
    // instead, using the same event path a keystroke would.
    useIsomorphicLayoutEffect(() => {
      const el = innerRef.current;
      if (!el) return;
      const typed = el.value;
      if (!typed) return;
      const controlled = props.value;
      if (controlled === undefined || String(controlled) === typed) return;
      props.onChange?.({
        ...({} as React.ChangeEvent<HTMLInputElement>),
        target: el,
        currentTarget: el,
      });
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    return (
      <input
        type={type}
        className={cn(
          "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-base shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
          className,
        )}
        ref={innerRef}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";

export { Input };
