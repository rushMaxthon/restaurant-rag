import { waitingLabel } from './delivered';

describe('after a delivery, what the second button says', () => {
  it('says nothing when the board is empty', () => {
    expect(waitingLabel(0)).toBeNull();
  });

  it('counts the orders waiting', () => {
    expect(waitingLabel(1)).toBe('1 order waiting');
    expect(waitingLabel(3)).toBe('3 orders waiting');
  });
});
