/**
 * The bill, asked of the server, while the customer is still deciding.
 *
 * This exists because the app used to work the bill out itself: the delivery
 * fee was read off the branch as a flat `delivery_fee`, and tax was
 * `subtotal * 0.05` written into the cart screen. On a branch configured the
 * way a real one is — packaging, a platform fee, 18% on delivery — that came
 * out at 147 where the server charged 229.23, and it showed "Free delivery"
 * while the courier wanted 50. The customer saw one number and was charged
 * another, and the screen was the one that was wrong.
 *
 * So nothing here adds anything up. It sends the address and the subtotal and
 * renders what comes back, computed by the same code that charges.
 *
 * The three states a caller has to handle are deliberately separate:
 *
 * * `quote` — a real answer. Show it.
 * * `loading` — ask again when the address changed; keep showing the previous
 *   answer meanwhile ONLY if it was for the same address, which is what
 *   `quote` being cleared on an address change enforces.
 * * `error` — say the fee is worked out at checkout. Never print a fallback
 *   number: inventing one is the entire failure this replaced.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from '@services/api';
import type { DeliveryQuote } from '@/types/app';
import {
  buildQuoteRequest,
  isQuotable,
  quoteCacheKey,
  type DeliveryQuoteInput,
} from '@utils/deliveryQuote';

export type { DeliveryQuoteInput };

export interface DeliveryQuoteState {
  quote: DeliveryQuote | null;
  loading: boolean;
  /** A sentence for the customer, or null. Never a number. */
  error: string | null;
  refresh: () => void;
}

/** How long to wait after the last keystroke before asking. */
const DEBOUNCE_MS = 600;

export function useDeliveryQuote(
  token: string | null,
  input: DeliveryQuoteInput,
  enabled: boolean,
): DeliveryQuoteState {
  const [quote, setQuote] = useState<DeliveryQuote | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const key = quoteCacheKey(input, enabled);

  // The request this hook is currently willing to accept an answer from.
  // Without it a slow reply for an old address lands after a fast one for the
  // new address and prices the wrong trip.
  const current = useRef(0);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    const generation = current.current + 1;
    current.current = generation;

    if (!enabled || !token || !isQuotable(input)) {
      // Clear rather than keep: a stale fee next to a changed address is the
      // one failure worse than no fee, because it looks correct.
      setQuote(null);
      setLoading(false);
      setError(null);
      return;
    }

    setLoading(true);
    const timer = setTimeout(() => {
      // Fire-and-forget on purpose: the generation guard below decides whether
      // the answer is still wanted, so there is nothing for the caller to
      // await and nothing to unhandle.
      const ask = async (): Promise<void> => {
        try {
          const result = await api.quoteDelivery(
            token,
            buildQuoteRequest(input),
          );
          if (current.current !== generation) return;
          setQuote(result);
          setError(null);
        } catch (requestError) {
          if (current.current !== generation) return;
          setQuote(null);
          setError(
            requestError instanceof Error
              ? requestError.message
              : 'Could not work out delivery just now.',
          );
        } finally {
          if (current.current === generation) setLoading(false);
        }
      };
      ask().catch(() => {
        // `ask` already records the failure in state; this only stops an
        // unhandled rejection if `setState` itself ever throws.
      });
    }, DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
    };
    // `key` carries every input the price depends on; `input` itself is a new
    // object each render and would re-ask forever.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, token, nonce]);

  return { quote, loading, error, refresh };
}
