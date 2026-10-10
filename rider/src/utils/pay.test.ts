import { earningLabel, rateCard, type RiderPay } from './pay';

const pay: RiderPay = {
  slabs: [
    { up_to_km: 3, amount: '25' },
    { up_to_km: 3.5, amount: '25' },
    { up_to_km: 4, amount: '30' },
    { up_to_km: 8, amount: '50' },
  ],
  incentive: '5',
  minimum: '25',
};

describe('rateCard', () => {
  it('reads each slab as a range, the first from zero', () => {
    expect(rateCard(pay).rows).toEqual([
      { from: 0, to: 3, amount: 25 },
      { from: 3, to: 3.5, amount: 25 },
      { from: 3.5, to: 4, amount: 30 },
      { from: 4, to: 8, amount: 50 },
    ]);
  });

  it('carries the incentive and where the card ends', () => {
    const card = rateCard(pay);
    expect(card.incentive).toBe(5);
    expect(card.lastKm).toBe(8);
    expect(card.lowest).toBe(25);
    expect(card.highest).toBe(50);
  });
});

describe('earningLabel', () => {
  it('formats an amount as rupees', () => {
    expect(earningLabel('35.00', 'Priced by the team')).toBe('₹35');
  });

  it('says a long trip is priced by hand instead of showing ₹0', () => {
    expect(earningLabel(null, 'Priced by the team')).toBe('Priced by the team');
    expect(earningLabel(undefined, 'Priced by the team')).toBe(
      'Priced by the team',
    );
  });
});
