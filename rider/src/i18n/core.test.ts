import { detectLanguage, fill, resolveLanguage } from './core';

describe('which language the phone asks for', () => {
  it('picks Hindi and Gujarati from the phone locale, whatever the region', () => {
    expect(detectLanguage('hi-IN')).toBe('hi');
    expect(detectLanguage('gu_IN')).toBe('gu');
    expect(detectLanguage('hi')).toBe('hi');
  });

  it('falls back to English for anything else, or nothing', () => {
    expect(detectLanguage('en-IN')).toBe('en');
    expect(detectLanguage('mr-IN')).toBe('en');
    expect(detectLanguage(undefined)).toBe('en');
    expect(detectLanguage('')).toBe('en');
  });
});

describe('the rider choice beats the phone', () => {
  it('follows the phone only while the choice is "system"', () => {
    expect(resolveLanguage('system', 'gu-IN')).toBe('gu');
    expect(resolveLanguage('hi', 'gu-IN')).toBe('hi');
    expect(resolveLanguage('en', 'hi-IN')).toBe('en');
  });
});

describe('filling in a sentence', () => {
  it('puts each value where its name is', () => {
    expect(fill('{n} orders near {place}', { n: 3, place: 'Adajan' })).toBe(
      '3 orders near Adajan',
    );
  });

  it('leaves an unknown name visible rather than printing "undefined"', () => {
    expect(fill('Hello {name}', {})).toBe('Hello {name}');
  });
});
