/**
 * Pick an address instead of typing one.
 *
 * The accurate way to get a customer's coordinates is not to geocode what they
 * typed — it is to have them choose a real place and take the coordinates from
 * that place's own record. Nothing is parsed, interpolated or guessed, and the
 * courier prices the trip to the building the customer pointed at.
 *
 * Three things about the shape of this:
 *
 * **It talks to our own backend, not to a map provider's JavaScript.** The
 * usual build loads the provider's script with an API key in the bundle. That
 * works, and referrer restrictions make it defensible, but it puts a key with a
 * billing quota in public. Our server holds the key, manages the session token
 * that makes autocomplete billed per session rather than per keystroke, and
 * stores the resolved coordinates on the customer's saved address so their next
 * order needs no lookup at all.
 *
 * **It degrades to a plain text box.** When no provider is configured the
 * backend answers `available: false`, the dropdown never appears, and the field
 * behaves exactly as it did before. The order is still priced, by the backend
 * geocoder. A missing dropdown costs accuracy, never correctness.
 *
 * **Typing always wins.** The box is never read-only and a picked address can
 * be edited afterwards — flat numbers and gate instructions are things only the
 * customer knows. Editing clears the stored coordinate, because the point that
 * was resolved no longer describes what is in the box.
 */

import { useCallback, useEffect, useId, useRef, useState } from "react";

import { Input } from "@/components/ui/input";
import { api, type Suggestion } from "@/lib/api";

/** What a picked place resolved to, for the form to fill itself in from. */
export type PickedAddress = {
  line1: string;
  line2: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  formatted: string;
  latitude: number;
  longitude: number;
  confidence: string;
};

/**
 * A token that ties one typing session to its final lookup.
 *
 * Map providers bill autocomplete per SESSION when the keystrokes and the
 * details call share a token, and per REQUEST when they do not. A fresh token
 * per component instance, replaced after each pick, is what keeps a twenty
 * character address one charge instead of twenty.
 *
 * `crypto.randomUUID` is unavailable over plain http on some browsers, which is
 * every developer's machine, so there is a fallback. The token only has to be
 * unique, not unguessable.
 */
function newSessionToken(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `s-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  }
}

export function AddressAutocomplete({
  value,
  onTextChange,
  onPick,
  locationId,
  inputId,
  placeholder,
  autoComplete,
  onBlur,
  invalid,
  icon,
}: {
  value: string;
  /** Every keystroke. The parent owns the text; this component owns the list. */
  onTextChange: (next: string) => void;
  /** A place was chosen, with coordinates. */
  onPick: (picked: PickedAddress) => void;
  locationId?: string | null;
  inputId: string;
  placeholder: string;
  autoComplete: string;
  onBlur: () => void;
  invalid?: boolean;
  /** The same leading glyph the sibling fields carry, so the row matches. */
  icon?: React.ReactNode;
}) {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const [resolving, setResolving] = useState(false);
  // Null until the first reply. Distinguishes "no provider configured" from
  // "nothing matched yet", which look identical in an empty list and mean
  // opposite things to the person reading the screen.
  const [available, setAvailable] = useState<boolean | null>(null);

  const session = useRef(newSessionToken());
  const listId = useId();
  // Bumped on every request so a slow reply for "12 M" cannot overwrite the
  // list for "12 MG Road". Without it the dropdown flickers backwards on a
  // slow connection, which is exactly when it is least usable.
  const asked = useRef(0);
  // Set while a pick is being applied, so the debounce that the pick's own
  // text change triggers does not immediately reopen the list underneath it.
  const justPicked = useRef(false);

  useEffect(() => {
    if (justPicked.current) {
      justPicked.current = false;
      return;
    }
    const text = value.trim();
    // Under three characters every query matches half a city, and each one is
    // a billable request.
    if (text.length < 3 || available === false) {
      setSuggestions([]);
      setOpen(false);
      return;
    }
    const mine = ++asked.current;
    // 250ms: long enough that a normal typing run is one request rather than
    // one per letter, short enough that the list does not feel late.
    const timer = setTimeout(async () => {
      try {
        const reply = await api.suggestAddresses({
          text,
          session_token: session.current,
          restaurant_location_id: locationId ?? undefined,
        });
        if (mine !== asked.current) return;
        setAvailable(reply.available);
        setSuggestions(reply.suggestions);
        setOpen(reply.suggestions.length > 0);
        setHighlighted(-1);
      } catch {
        // A typing box must never throw. No list is the honest outcome, and
        // the text the customer typed is still a usable address.
        if (mine === asked.current) {
          setSuggestions([]);
          setOpen(false);
        }
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [value, locationId, available]);

  const choose = useCallback(
    async (suggestion: Suggestion) => {
      setOpen(false);
      setResolving(true);
      justPicked.current = true;
      try {
        const resolved = await api.resolveAddress({
          place_id: suggestion.place_id,
          session_token: session.current,
        });
        // The session ends with the details call it paid for. A new one starts
        // here so a second address in the same visit is billed separately
        // rather than extending the first forever.
        session.current = newSessionToken();
        onPick(resolved);
      } catch {
        // The customer picked something and we could not resolve it. Their
        // typed text stands, and the backend geocoder will still price it.
        justPicked.current = false;
      } finally {
        setResolving(false);
      }
    },
    [onPick],
  );

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || suggestions.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlighted((at) => (at + 1) % suggestions.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlighted((at) => (at <= 0 ? suggestions.length - 1 : at - 1));
    } else if (event.key === "Enter" && highlighted >= 0) {
      // Only when something is highlighted. Swallowing a bare Enter would stop
      // somebody submitting a form with an address they typed themselves.
      event.preventDefault();
      void choose(suggestions[highlighted]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="relative">
      {/*
       * `field-wrap` + `Input`, exactly as every other box on this form. A bare
       * `<input>` here rendered with no border, no background and no height —
       * the styling lives on the shared component, not on the wrapper, so the
       * first address box looked like loose text beside five proper fields.
       */}
      <div className="field-wrap" data-invalid={invalid ? true : undefined}>
        {icon}
        <Input
          aria-activedescendant={highlighted >= 0 ? `${listId}-${highlighted}` : undefined}
          aria-autocomplete="list"
          aria-controls={open ? listId : undefined}
          aria-expanded={open}
          aria-invalid={invalid}
          autoComplete={autoComplete}
          className="h-12"
          id={inputId}
          onBlur={() => {
            // Deferred past the click that may be landing on an option: a
            // blur that closes the list immediately means the option is gone
            // before the click reaches it, and picking by mouse never works.
            setTimeout(() => setOpen(false), 150);
            onBlur();
          }}
          onChange={(event) => onTextChange(event.target.value)}
          onFocus={() => setOpen(suggestions.length > 0)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          role="combobox"
          type="text"
          value={value}
        />
      </div>

      {resolving && <p className="mt-1 text-xs text-muted">Looking up that address…</p>}

      {open && suggestions.length > 0 && (
        <ul
          className="elevated-panel absolute left-0 right-0 top-full z-30 mt-1 max-h-64 overflow-auto py-1"
          id={listId}
          role="listbox"
        >
          {suggestions.map((suggestion, at) => (
            <li
              aria-selected={at === highlighted}
              className={`cursor-pointer px-3 py-2 text-sm ${
                at === highlighted ? "bg-[var(--surface-alt)]" : ""
              }`}
              id={`${listId}-${at}`}
              key={suggestion.place_id}
              // Mouse DOWN, not click: the input's blur fires first on a
              // click and the list would already be closing.
              onMouseDown={(event) => {
                event.preventDefault();
                void choose(suggestion);
              }}
              onMouseEnter={() => setHighlighted(at)}
              role="option"
            >
              <span className="block font-semibold">{suggestion.primary}</span>
              {suggestion.secondary && (
                <span className="block text-xs text-muted">{suggestion.secondary}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
