import { CircleAlert } from 'lucide-react';

import { useMoney } from '../hooks/useMoney';

/**
 * Says so when a total spans restaurants that charge in different money.
 *
 * ₹40,000 plus $500 is not 40,500 of anything. Once one restaurant on the
 * platform charges in rupees and another in dollars, a platform-wide revenue
 * figure stops being a number and becomes a sum of two different units
 * printed under whichever symbol happened to win.
 *
 * Saying so beats the alternatives. Hiding the figure makes the page useless
 * for the common case where every tenant does share a currency; converting
 * silently invents an exchange rate nobody chose and that nobody's accountant
 * would accept; and printing it unlabelled is what we were already doing,
 * which is the bug.
 *
 * It renders nothing at all when the question does not arise — one tenant in
 * scope, or every tenant charging the same — so the usual case stays clean.
 */
interface MixedCurrencyNoticeProps {
  /** What the figures on this page are, for the sentence: "Revenue totals". */
  subject?: string;
}

export function MixedCurrencyNotice({ subject = 'Totals' }: MixedCurrencyNoticeProps) {
  const money = useMoney();

  if (!money.mixed) {
    return null;
  }

  return (
    <p className="mixed-currency" role="note">
      <CircleAlert size={15} strokeWidth={2.2} />
      <span>
        <strong>{subject} span more than one currency.</strong> Restaurants on this
        platform charge in different money, so the figures below are added together
        without being converted. Pick a restaurant above to read one restaurant's
        numbers in its own currency.
      </span>
    </p>
  );
}
