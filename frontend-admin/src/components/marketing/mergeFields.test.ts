import { describe, expect, it } from 'vitest';
import {
  buildPreviewRecipients,
  findUnknownTokens,
  resolveMergeFields,
} from './mergeFields';

describe('resolveMergeFields', () => {
  it('substitutes the values it is given', () => {
    expect(
      resolveMergeFields('We miss you, {first_name}, at {branch}!', {
        first_name: 'Priya',
        branch: 'Indiranagar',
      }),
    ).toBe('We miss you, Priya, at Indiranagar!');
  });

  // The whole reason this module exists: a customer with no name on file must
  // never be sent "Hi {first_name}" or "Hi null".
  it('falls back rather than leaving a token or printing null', () => {
    const result = resolveMergeFields('Hi {first_name} from {branch}', {
      first_name: null,
      branch: null,
    });
    expect(result).toBe('Hi there from our kitchen');
    expect(result).not.toContain('{');
    expect(result).not.toContain('null');
  });

  it('treats a blank or whitespace-only name as missing', () => {
    expect(
      resolveMergeFields('Hi {first_name}', { first_name: '   ', branch: null }),
    ).toBe('Hi there');
  });

  it('replaces every occurrence, not just the first', () => {
    expect(
      resolveMergeFields('{first_name}, really {first_name}', {
        first_name: 'Arjun',
        branch: null,
      }),
    ).toBe('Arjun, really Arjun');
  });
});

describe('findUnknownTokens', () => {
  it('finds a token nothing can fill', () => {
    expect(findUnknownTokens('Hi {first_name}, your {order_id} is ready')).toEqual([
      '{order_id}',
    ]);
  });

  it('accepts the known fields', () => {
    expect(findUnknownTokens('Hi {first_name} at {branch}')).toEqual([]);
  });

  it('reports each unknown token once', () => {
    expect(findUnknownTokens('{nope} and {nope} again')).toEqual(['{nope}']);
  });
});

describe('buildPreviewRecipients', () => {
  it('always ends on the recipient with no name', () => {
    const recipients = buildPreviewRecipients('Indiranagar');
    expect(recipients.length).toBeGreaterThan(1);
    expect(recipients[recipients.length - 1].first_name).toBeNull();
  });

  it('carries the chosen branch onto every recipient', () => {
    for (const recipient of buildPreviewRecipients('Koramangala')) {
      expect(recipient.branch).toBe('Koramangala');
    }
  });
});
