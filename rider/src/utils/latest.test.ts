import { sequencer } from './latest';

describe('only the newest answer may land', () => {
  it('drops an answer to a request that was overtaken', () => {
    const seq = sequencer();
    const first = seq.start();
    const second = seq.start();
    expect(seq.isLatest(first)).toBe(false);
    expect(seq.isLatest(second)).toBe(true);
  });

  it('drops a poll that was already on its way when a newer value was set by hand', () => {
    const seq = sequencer();
    const poll = seq.start();
    seq.invalidate(); // e.g. "go online" just returned the new status
    expect(seq.isLatest(poll)).toBe(false);
  });
});
