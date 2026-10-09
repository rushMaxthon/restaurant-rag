import {
  decodeSeen,
  encodeSeen,
  isSeen,
  markSeen,
  resetAll,
} from './guideStore';

describe('which tours a rider has already seen', () => {
  it('starts with nothing seen', () => {
    expect(isSeen({}, 'home')).toBe(false);
  });

  it('marks one tour seen without touching the others', () => {
    const seen = markSeen({ intro: true }, 'home');
    expect(seen).toEqual({ intro: true, home: true });
    expect(isSeen(seen, 'home')).toBe(true);
    expect(isSeen(seen, 'orders')).toBe(false);
  });

  it('round-trips through storage', () => {
    expect(decodeSeen(encodeSeen({ home: true, otp: true }))).toEqual({
      home: true,
      otp: true,
    });
  });

  it('treats garbage in storage as nothing seen, so a bad write cannot hide the guide', () => {
    expect(decodeSeen(null)).toEqual({});
    expect(decodeSeen('not json')).toEqual({});
    expect(decodeSeen('[1,2]')).toEqual({});
    expect(decodeSeen('{"home": "yes", "intro": true, "x": 1}')).toEqual({
      intro: true,
    });
  });

  it('"show tips again" forgets everything except the intro', () => {
    expect(resetAll({ intro: true, home: true, trip: true })).toEqual({
      intro: true,
    });
  });
});
