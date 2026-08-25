import { describe, expect, it } from 'vitest';
import { describeAge, groupChatSessions } from './chatSessions';
import type { OwnerChatHistoryItem } from '../../types/app';

function msg(
  session: string,
  role: 'USER' | 'ASSISTANT',
  message: string,
  created_at: string,
): OwnerChatHistoryItem {
  return { id: `${session}-${created_at}`, session_id: session, role, message,
           skill: null, answer_source: null, created_at };
}

describe('groupChatSessions', () => {
  // The real response: flat, oldest-first, every session interleaved.
  const history = [
    msg('a', 'USER', 'hello', '2026-08-21T13:06:15Z'),
    msg('a', 'ASSISTANT', 'Hi there', '2026-08-21T13:06:18Z'),
    msg('b', 'USER', 'Why are my sales down?', '2026-08-24T09:00:00Z'),
    msg('b', 'ASSISTANT', 'Sales are up by ₹622…', '2026-08-24T09:00:09Z'),
  ];

  it('groups the flat list into one entry per session', () => {
    expect(groupChatSessions(history).map((s) => s.id)).toEqual(['b', 'a']);
  });

  it('orders newest conversation first', () => {
    const [newest] = groupChatSessions(history);
    expect(newest.id).toBe('b');
    expect(newest.lastActivity).toBe('2026-08-24T09:00:09Z');
  });

  it("titles a thread from the owner's first question", () => {
    const byId = new Map(groupChatSessions(history).map((s) => [s.id, s]));
    expect(byId.get('b')?.title).toBe('Why are my sales down?');
    expect(byId.get('a')?.title).toBe('hello');
  });

  it('truncates a long question on a word boundary', () => {
    const long = groupChatSessions([
      msg('c', 'USER', 'Why did my afternoon revenue collapse across every branch last quarter', '2026-08-25T10:00:00Z'),
    ]);
    expect(long[0].title.endsWith('…')).toBe(true);
    expect(long[0].title.length).toBeLessThanOrEqual(45);
    expect(long[0].title).not.toMatch(/\s…$/);
  });

  it('keeps each conversation ordered oldest-first for replay', () => {
    const shuffled = [history[3], history[2]];
    const [session] = groupChatSessions(shuffled);
    expect(session.messages.map((m) => m.role)).toEqual(['USER', 'ASSISTANT']);
  });

  it('counts messages per conversation', () => {
    expect(groupChatSessions(history).every((s) => s.messageCount === 2)).toBe(true);
  });

  it('handles an empty history', () => {
    expect(groupChatSessions([])).toEqual([]);
  });
});

describe('describeAge', () => {
  const now = new Date('2026-08-25T12:00:00Z');
  it('describes recent activity in relative terms', () => {
    expect(describeAge('2026-08-25T11:59:40Z', now)).toBe('Just now');
    expect(describeAge('2026-08-25T11:30:00Z', now)).toBe('30m ago');
    expect(describeAge('2026-08-25T09:00:00Z', now)).toBe('3h ago');
    expect(describeAge('2026-08-23T12:00:00Z', now)).toBe('2d ago');
  });
  it('falls back to a date once a week has passed', () => {
    expect(describeAge('2026-08-01T12:00:00Z', now)).toMatch(/1 Aug/);
  });
  it('returns nothing for an unparseable timestamp', () => {
    expect(describeAge('not-a-date', now)).toBe('');
  });
});
