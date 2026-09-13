/**
 * `DishRow` is the single storefront dish component, replacing `DishCard` and
 * `MenuItemCard`. Those two drifted apart while rendering the same record, and
 * the differences that mattered — the offer flag, an `onDecrease` that took an
 * item in one and an id in the other — were drift rather than design.
 *
 * These tests fix the behaviour that drift was hiding, so the consolidation has
 * something to land in. They assert what a customer can see and press, never
 * class names: a restyle should not turn this file red.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { DishRow } from './DishRow';
import type { MenuItem } from '../../types/app';

function makeItem(overrides: Partial<MenuItem> = {}): MenuItem {
  return {
    id: 'item-1',
    restaurant_id: 'restaurant-1',
    restaurant_location_id: 'location-1',
    restaurant_location_name: 'Bangkok Bowl Ellisbridge',
    restaurant_location_city: 'Ahmedabad',
    name: 'Pad Thai Veg',
    category: 'Main Course',
    cuisine_type: 'Thai',
    description: 'Rice noodles tossed with tamarind and peanuts.',
    price: '249.00',
    is_veg: true,
    is_available: true,
    is_bestseller: false,
    image_url: null,
    popularity_score: '10',
    rating: null,
    rating_count: 0,
    launched_at: '2026-09-01T00:00:00Z',
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    is_new_launch: false,
    is_new: false,
    is_favorite: false,
    has_sizes: false,
    has_customizations: false,
    sizes: [],
    customization_groups: [],
    ...overrides,
  };
}

function renderDishRow(props: Partial<React.ComponentProps<typeof DishRow>> = {}) {
  const onAdd = vi.fn();
  const onDecrease = vi.fn();
  const onOpen = vi.fn();

  render(
    <DishRow
      item={makeItem()}
      onAdd={onAdd}
      onDecrease={onDecrease}
      onOpen={onOpen}
      quantity={0}
      {...props}
    />,
  );

  return { onAdd, onDecrease, onOpen };
}

describe('DishRow', () => {
  it('shows the dish name and its price', () => {
    renderDishRow();

    expect(screen.getByText('Pad Thai Veg')).toBeInTheDocument();
    expect(screen.getByText(/249/)).toBeInTheDocument();
  });

  it('offers an add control when the dish is not yet in the cart', async () => {
    const { onAdd } = renderDishRow({ quantity: 0 });

    await userEvent.click(screen.getByRole('button', { name: /add/i }));

    expect(onAdd).toHaveBeenCalledTimes(1);
  });

  it('replaces the add control with a stepper once the dish is in the cart', () => {
    renderDishRow({ quantity: 2 });

    expect(screen.queryByRole('button', { name: /^add$/i })).not.toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  /**
   * The drift that made this consolidation worth doing: `DishCard` called
   * `onDecrease(item.id)` and `MenuItemCard` called `onDecrease(item)`, so a
   * caller written against one silently mis-handled the other. `DishRow` passes
   * the id, because that is what every existing caller's handler expects.
   */
  it('passes the item id when decreasing, not the item', async () => {
    const { onDecrease } = renderDishRow({ quantity: 1 });

    await userEvent.click(screen.getByRole('button', { name: /remove one/i }));

    expect(onDecrease).toHaveBeenCalledWith('item-1');
  });

  it('refuses to add a dish that is sold out', async () => {
    const { onAdd } = renderDishRow({ item: makeItem({ is_available: false }) });

    expect(screen.getByText(/sold out/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^add$/i })).not.toBeInTheDocument();
    expect(onAdd).not.toHaveBeenCalled();
  });

  /**
   * A size-priced dish has no single price. Quoting the cheapest size flat
   * reads as the price of the dish the customer is looking at, which it is not.
   */
  it('marks the price as a starting price when the dish is sold by size', () => {
    renderDishRow({ item: makeItem({ has_sizes: true }) });

    expect(screen.getByText(/from/i)).toBeInTheDocument();
  });

  it('marks a vegetarian dish for people who filter on it', () => {
    renderDishRow({ item: makeItem({ is_veg: true }) });

    expect(screen.getByTitle('Vegetarian')).toBeInTheDocument();
  });

  it('marks a non-vegetarian dish', () => {
    renderDishRow({ item: makeItem({ is_veg: false }) });

    expect(screen.getByTitle('Non-vegetarian')).toBeInTheDocument();
  });

  it('opens the dish when its name is pressed', async () => {
    const { onOpen } = renderDishRow();

    await userEvent.click(screen.getByText('Pad Thai Veg'));

    expect(onOpen).toHaveBeenCalledWith('item-1');
  });

  /**
   * `MenuItemCard` carried this and `DishCard` did not, which is the whole
   * reason the restaurant page and the home page disagreed about the same dish.
   */
  it('signals an available offer when the caller reports one', () => {
    renderDishRow({ hasOfferAvailable: true });

    expect(screen.getByText(/offer/i)).toBeInTheDocument();
  });

  it('says nothing about offers when there is none', () => {
    renderDishRow({ hasOfferAvailable: false });

    expect(screen.queryByText(/offer/i)).not.toBeInTheDocument();
  });

  /**
   * At most one badge. Two stacked labels stop being a signal and start being
   * noise, and "new" is the more perishable of the two.
   */
  it('prefers the new badge over the popular badge when a dish is both', () => {
    renderDishRow({ item: makeItem({ is_new: true, is_bestseller: true }) });

    expect(screen.getByText(/new/i)).toBeInTheDocument();
    expect(screen.queryByText(/popular/i)).not.toBeInTheDocument();
  });

  it('omits the favorite control when the caller cannot handle it', () => {
    renderDishRow({ onToggleFavorite: undefined });

    expect(screen.queryByRole('button', { name: /favorite/i })).not.toBeInTheDocument();
  });

  it('reports the dish when the favorite control is pressed', async () => {
    const onToggleFavorite = vi.fn();
    renderDishRow({ onToggleFavorite });

    await userEvent.click(screen.getByRole('button', { name: /add to favorites/i }));

    expect(onToggleFavorite).toHaveBeenCalledWith(expect.objectContaining({ id: 'item-1' }));
  });
});
