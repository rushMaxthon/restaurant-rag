import { dedupeById, splitBoldSegments } from './chatText';

describe('splitBoldSegments', () => {
  it('returns plain text untouched', () => {
    expect(splitBoldSegments('hello there')).toEqual([
      { text: 'hello there', bold: false },
    ]);
  });

  it('splits bold spans out of the text', () => {
    expect(
      splitBoldSegments('We do have **spicy momos**! The **Jhol Momos** rock.'),
    ).toEqual([
      { text: 'We do have ', bold: false },
      { text: 'spicy momos', bold: true },
      { text: '! The ', bold: false },
      { text: 'Jhol Momos', bold: true },
      { text: ' rock.', bold: false },
    ]);
  });

  it('strips unpaired markers instead of showing them', () => {
    expect(splitBoldSegments('mid-stream **partial')).toEqual([
      { text: 'mid-stream partial', bold: false },
    ]);
  });

  it('handles a bold span at the start and end', () => {
    expect(splitBoldSegments('**Kung Pao Chicken** is Rs. 29.96')).toEqual([
      { text: 'Kung Pao Chicken', bold: true },
      { text: ' is Rs. 29.96', bold: false },
    ]);
  });
});

describe('dedupeById', () => {
  it('keeps first occurrence and drops repeats', () => {
    const rows = [{ id: 'a' }, { id: 'b' }, { id: 'a' }];
    expect(dedupeById(rows)).toEqual([{ id: 'a' }, { id: 'b' }]);
  });
});
