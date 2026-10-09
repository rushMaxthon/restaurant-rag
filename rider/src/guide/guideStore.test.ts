import {
  afterTour,
  unseenTargets,
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

describe('a tour that could only show some of its tips', () => {
  const targets = ['home.toggle', 'home.today'];

  it('is not done while a tip was never shown', () => {
    const seen = afterTour({}, 'home', targets, ['home.toggle'], false);
    expect(isSeen(seen, 'home')).toBe(false);
    expect(unseenTargets(seen, 'home', targets)).toEqual(['home.today']);
  });

  it('is done once every tip has been shown, across visits', () => {
    let seen = afterTour({}, 'home', targets, ['home.toggle'], false);
    seen = afterTour(seen, 'home', targets, ['home.today'], false);
    expect(isSeen(seen, 'home')).toBe(true);
  });

  it('is done at once when the rider skips it', () => {
    const seen = afterTour({}, 'home', targets, ['home.toggle'], true);
    expect(isSeen(seen, 'home')).toBe(true);
  });

  it('starts over after "Show tips again"', () => {
    const seen = afterTour({ intro: true }, 'home', targets, ['home.toggle'], false);
    expect(unseenTargets(resetAll(seen), 'home', targets)).toEqual(targets);
  });
});
