/**
 * "Who should see this post?" — the social half of step 3.
 *
 * Nothing on this screen exists on the direct one, and that is the point. A
 * public post has no segment to choose, no consent to check, no minimum
 * audience to clear and no reachable count to itemise. Every one of those
 * controls would be a lie here, so instead of hiding six disabled fields the
 * social flow asks the two questions that are real: which branch is this
 * about, and are you paying to push it further.
 *
 * Money is the largest thing on the screen because it is the only irreversible
 * thing on it. Reach on a boost is Meta's estimate, and it is labelled as
 * Meta's estimate — the Hub does not put its own name on a number it cannot
 * verify against a fact pack.
 */

import { Check, MapPin, Megaphone, Users } from 'lucide-react';
import { formatCurrency } from '../../services/api';
import { marketingReference } from '../../services/marketing/marketingApi';
import { getChannel } from './channels';
import type { CampaignContentExtra, MarketingChannel } from '../../services/marketing/types';

interface SocialAudienceStepProps {
  channel: MarketingChannel;
  branchIds: string[];
  extra: CampaignContentExtra;
  onBranch: (branchId: string) => void;
  onExtra: (changes: Partial<CampaignContentExtra>) => void;
}

const BUDGETS = [300, 500, 1000, 2500];
const DURATIONS = [1, 3, 7];
const RADII = [2, 5, 10];

/**
 * A very rough impressions band for a budget, labelled as Meta's to guess.
 *
 * Deliberately a wide range and deliberately not presented as ours. A single
 * confident number here would be the one figure in the Hub that nothing can
 * check — the opposite of how every other number in this product is produced.
 */
function impressionsBand(budget: number, days: number): string {
  const low = Math.round((budget * days * 12) / 10) * 10;
  const high = low * 2;
  return `${low.toLocaleString('en-CA')}–${high.toLocaleString('en-CA')}`;
}

export function SocialAudienceStep({
  channel,
  branchIds,
  extra,
  onBranch,
  onExtra,
}: SocialAudienceStepProps) {
  const definition = getChannel(channel);
  const boosting = (extra.boost_budget ?? 0) > 0;
  const days = extra.boost_days ?? 3;
  const radius = extra.boost_radius_km ?? 5;

  return (
    <>
      <div className="mkt-section">
        <span className="mkt-section__label">
          Which branch is this about? <span>It decides how the post is reported</span>
        </span>
        <div aria-label="Branches" className="mkt-grid mkt-grid--2" role="group">
          {marketingReference.branches.map((branch) => {
            const isSelected = branchIds.includes(branch.id);
            return (
              <button
                aria-checked={isSelected}
                className={
                  isSelected ? 'mkt-pick mkt-pick--row mkt-pick--selected' : 'mkt-pick mkt-pick--row'
                }
                key={branch.id}
                onClick={() => onBranch(branch.id)}
                role="checkbox"
                type="button"
              >
                <span aria-hidden="true" className="mkt-pick__icon">
                  <MapPin size={17} strokeWidth={2.2} />
                </span>
                <span className="mkt-pick__copy">
                  <span className="mkt-pick__title">
                    {branch.branch_name}
                    {branch.is_active ? '' : ' · inactive'}
                  </span>
                  <span className="mkt-pick__text">
                    {branch.city}, {branch.state}
                  </span>
                </span>
                <span aria-hidden="true" className="mkt-pick__tick">
                  <Check size={12} strokeWidth={3.4} />
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="mkt-section">
        <span className="mkt-section__label">
          How far should it go? <span>You can change this after it is posted</span>
        </span>

        <div className="mkt-grid mkt-grid--2">
          <button
            aria-pressed={!boosting}
            className={!boosting ? 'mkt-pick mkt-pick--selected' : 'mkt-pick'}
            onClick={() => onExtra({ boost_budget: null })}
            type="button"
          >
            <span aria-hidden="true" className="mkt-pick__tick">
              <Check size={12} strokeWidth={3.4} />
            </span>
            <span aria-hidden="true" className="mkt-pick__icon">
              <Users size={18} strokeWidth={2.1} />
            </span>
            <span className="mkt-pick__title">Just my followers</span>
            <span className="mkt-pick__text">
              Free. The people who already follow you on {definition.label}.
            </span>
          </button>

          <button
            aria-pressed={boosting}
            className={boosting ? 'mkt-pick mkt-pick--selected' : 'mkt-pick'}
            onClick={() =>
              onExtra({
                boost_budget: extra.boost_budget ?? BUDGETS[1],
                boost_days: days,
                boost_radius_km: radius,
              })
            }
            type="button"
          >
            <span aria-hidden="true" className="mkt-pick__tick">
              <Check size={12} strokeWidth={3.4} />
            </span>
            <span aria-hidden="true" className="mkt-pick__icon">
              <Megaphone size={18} strokeWidth={2.1} />
            </span>
            <span className="mkt-pick__title">Pay to reach more people</span>
            <span className="mkt-pick__text">
              Shows it to people near you who do not follow you yet.
            </span>
          </button>
        </div>

        {boosting ? (
          <div className="mkt-boost">
            <div className="mkt-boost__field">
              <span className="mkt-field__label">Budget</span>
              <div className="mkt-chips">
                {BUDGETS.map((amount) => (
                  <button
                    className={
                      extra.boost_budget === amount ? 'mkt-chip mkt-chip--on' : 'mkt-chip'
                    }
                    key={amount}
                    onClick={() => onExtra({ boost_budget: amount })}
                    type="button"
                  >
                    {formatCurrency(amount)}
                  </button>
                ))}
              </div>
            </div>

            <div className="mkt-boost__field">
              <span className="mkt-field__label">Over how long</span>
              <div className="mkt-chips">
                {DURATIONS.map((value) => (
                  <button
                    className={days === value ? 'mkt-chip mkt-chip--on' : 'mkt-chip'}
                    key={value}
                    onClick={() => onExtra({ boost_days: value })}
                    type="button"
                  >
                    {value === 1 ? '1 day' : `${value} days`}
                  </button>
                ))}
              </div>
            </div>

            <div className="mkt-boost__field">
              <span className="mkt-field__label">How near</span>
              <div className="mkt-chips">
                {RADII.map((value) => (
                  <button
                    className={radius === value ? 'mkt-chip mkt-chip--on' : 'mkt-chip'}
                    key={value}
                    onClick={() => onExtra({ boost_radius_km: value })}
                    type="button"
                  >
                    Within {value} km
                  </button>
                ))}
              </div>
            </div>

            <p className="mkt-boost__total">
              <strong>{formatCurrency(extra.boost_budget ?? 0)}</strong> in total. Meta
              estimates {impressionsBand(extra.boost_budget ?? 0, days)} people will see it,
              and bills you directly — this charge does not come from us.
            </p>
          </div>
        ) : null}
      </div>
    </>
  );
}
