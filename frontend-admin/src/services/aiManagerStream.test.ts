import { describe, expect, it } from 'vitest';

import { parseSseBuffer, parseSseFrame } from './aiManagerStream';

/**
 * The frame parser is the one piece of the AI Manager UI with real logic: a
 * network chunk can split a frame anywhere, and a mis-split would either drop an
 * answer or render half a JSON blob to the owner.
 */

describe('parseSseFrame', () => {
  it('reads the event name and JSON payload', () => {
    const frame = parseSseFrame('event: meta\ndata: {"session_id": "abc", "skill": "metric_lookup"}');
    expect(frame).toEqual({
      event: 'meta',
      data: { session_id: 'abc', skill: 'metric_lookup' },
    });
  });

  it('defaults the event name when only data is present', () => {
    expect(parseSseFrame('data: {"text": "hello"}')?.event).toBe('message');
  });

  it('ignores comment and keep-alive lines', () => {
    expect(parseSseFrame(': keep-alive')).toBeNull();
    expect(parseSseFrame('')).toBeNull();
  });

  it('drops a frame whose JSON cannot be read rather than throwing', () => {
    // One unreadable frame must not tear down the rest of the answer.
    expect(parseSseFrame('event: token\ndata: {"text": "unterminated')).toBeNull();
  });

  it('joins multi-line data fields', () => {
    const frame = parseSseFrame('event: done\ndata: {"a": 1,\ndata: "b": 2}');
    expect(frame?.data).toEqual({ a: 1, b: 2 });
  });

  it('wraps a non-object payload so callers always get a record', () => {
    expect(parseSseFrame('data: 42')?.data).toEqual({ value: 42 });
  });
});

describe('parseSseBuffer', () => {
  it('extracts complete frames and keeps the remainder', () => {
    const buffer =
      'event: meta\ndata: {"session_id": "s1"}\n\nevent: token\ndata: {"text": "Revenue "}\n\nevent: tok';
    const { frames, rest } = parseSseBuffer(buffer);

    expect(frames).toHaveLength(2);
    expect(frames[0].event).toBe('meta');
    expect(frames[1].data.text).toBe('Revenue ');
    expect(rest).toBe('event: tok');
  });

  it('returns nothing when no frame is complete yet', () => {
    const { frames, rest } = parseSseBuffer('event: token\ndata: {"text": "par');
    expect(frames).toEqual([]);
    expect(rest).toBe('event: token\ndata: {"text": "par');
  });

  it('reassembles a frame split across two chunks', () => {
    // The realistic failure: a chunk boundary lands mid-JSON.
    const first = parseSseBuffer('event: token\ndata: {"text": "Revenue was ');
    expect(first.frames).toEqual([]);

    const second = parseSseBuffer(`${first.rest}5,000."}\n\n`);
    expect(second.frames).toHaveLength(1);
    expect(second.frames[0].data.text).toBe('Revenue was 5,000.');
  });

  it('handles a boundary that falls between the two newlines', () => {
    const first = parseSseBuffer('event: token\ndata: {"text": "a"}\n');
    expect(first.frames).toEqual([]);

    const second = parseSseBuffer(`${first.rest}\nevent: done\ndata: {"skill": "x"}\n\n`);
    expect(second.frames.map((frame) => frame.event)).toEqual(['token', 'done']);
  });

  it('parses CRLF line endings the same as LF', () => {
    // A proxy may rewrite line endings in transit.
    const { frames } = parseSseBuffer('event: meta\r\ndata: {"session_id": "s1"}\r\n\r\n');
    expect(frames).toHaveLength(1);
    expect(frames[0].data.session_id).toBe('s1');
  });

  it('leaves an empty remainder when the buffer ends cleanly', () => {
    const { rest } = parseSseBuffer('event: done\ndata: {"skill": "x"}\n\n');
    expect(rest).toBe('');
  });

  it('reads a full answer stream in order', () => {
    const stream = [
      'event: meta\ndata: {"session_id": "s1", "skill": "revenue_diagnosis", "answer_source": "TEMPLATE"}\n\n',
      'event: token\ndata: {"text": "Revenue was 5,000. "}\n\n',
      'event: token\ndata: {"text": "Margherita Pizza fell the most. "}\n\n',
      'event: done\ndata: {"session_id": "s1", "answer": "Revenue was 5,000."}\n\n',
    ].join('');

    const { frames, rest } = parseSseBuffer(stream);
    expect(frames.map((frame) => frame.event)).toEqual(['meta', 'token', 'token', 'done']);
    expect(rest).toBe('');

    const answer = frames
      .filter((frame) => frame.event === 'token')
      .map((frame) => frame.data.text)
      .join('');
    expect(answer).toBe('Revenue was 5,000. Margherita Pizza fell the most. ');
  });

  it('skips a malformed frame but keeps the ones around it', () => {
    const stream =
      'event: token\ndata: {"text": "good"}\n\nevent: token\ndata: {oops}\n\nevent: done\ndata: {"skill": "x"}\n\n';
    const { frames } = parseSseBuffer(stream);
    expect(frames.map((frame) => frame.event)).toEqual(['token', 'done']);
  });
});
