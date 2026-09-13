/**
 * The three image states, which exist because production has no upload
 * pipeline: an owner pastes a URL and the app hotlinks it. Links rot, so the
 * placeholder is not a rare fallback — it is where a share of dishes
 * permanently live, and it has to look deliberate rather than broken.
 *
 * `container.querySelector('img')` rather than `screen.getByRole('img')`:
 * this project's testing-library version resolves an `<img alt="">` to the
 * "presentation" role, not "img", so the role query does not find it.
 */

import { render, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DishMedia } from './DishMedia';

describe('DishMedia', () => {
  it('renders the photograph when the dish has one', () => {
    const { container } = render(
      <DishMedia imageUrl="https://example.com/pad-thai.jpg" name="Pad Thai" variant="grid" />,
    );

    expect(container.querySelector('img')).toHaveAttribute('src', 'https://example.com/pad-thai.jpg');
  });

  it('falls back to the branded placeholder when the dish has no photograph', () => {
    const { container } = render(<DishMedia imageUrl={null} name="Pad Thai" variant="grid" />);

    expect(container.querySelector('img')?.getAttribute('src')).toMatch(/^data:image\/svg\+xml/);
  });

  /**
   * The case that made this component worth extracting: a URL that 404s must
   * land on the SAME designed placeholder, never a broken-image frame.
   */
  it('falls back to the placeholder when the photograph fails to load', () => {
    const { container } = render(<DishMedia imageUrl="https://example.com/gone.jpg" name="Pad Thai" variant="grid" />);

    fireEvent.error(container.querySelector('img') as HTMLImageElement);

    expect(container.querySelector('img')?.getAttribute('src')).toMatch(/^data:image\/svg\+xml/);
  });

  it('derives the placeholder from the dish name, so the same dish looks the same', () => {
    const { container, unmount } = render(<DishMedia imageUrl={null} name="Pad Thai" variant="grid" />);
    const first = container.querySelector('img')?.getAttribute('src');
    unmount();

    const { container: second } = render(<DishMedia imageUrl={null} name="Pad Thai" variant="grid" />);

    expect(second.querySelector('img')?.getAttribute('src')).toBe(first);
  });

  it('gives different dishes different placeholders', () => {
    const { container, unmount } = render(<DishMedia imageUrl={null} name="Pad Thai" variant="grid" />);
    const first = container.querySelector('img')?.getAttribute('src');
    unmount();

    const { container: second } = render(<DishMedia imageUrl={null} name="Green Curry" variant="grid" />);

    expect(second.querySelector('img')?.getAttribute('src')).not.toBe(first);
  });

  /**
   * Lazy loading and async decoding are not decoration here: an owner can
   * paste a 5MB 4000px PNG and nothing resizes it, so a grid of them must not
   * block first paint.
   */
  it('loads lazily and decodes off the main thread', () => {
    const { container } = render(<DishMedia imageUrl="https://example.com/pad-thai.jpg" name="Pad Thai" variant="grid" />);

    const img = container.querySelector('img');
    expect(img).toHaveAttribute('loading', 'lazy');
    expect(img).toHaveAttribute('decoding', 'async');
  });

  it('marks the image decorative, because the dish name is already adjacent text', () => {
    const { container } = render(<DishMedia imageUrl="https://example.com/pad-thai.jpg" name="Pad Thai" variant="grid" />);

    expect(container.querySelector('img')).toHaveAttribute('alt', '');
  });
});
