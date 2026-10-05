import { isOnSale } from './stock';

describe('isOnSale', () => {
  it('is on sale when nothing says otherwise', () => {
    expect(isOnSale({ is_available: true })).toBe(true);
    expect(isOnSale({ is_available: true, stock_quantity: null })).toBe(true);
    expect(isOnSale({ is_available: true, stock_quantity: 4 })).toBe(true);
  });

  it('treats a payload with no availability field as available', () => {
    expect(isOnSale({})).toBe(true);
  });

  it('is not on sale when the owner hid it', () => {
    expect(isOnSale({ is_available: false, stock_quantity: 9 })).toBe(false);
  });

  it('is not on sale when counted down to zero', () => {
    expect(isOnSale({ is_available: true, stock_quantity: 0 })).toBe(false);
  });

  it('is not on sale when marked out of stock by hand, whatever the count', () => {
    expect(isOnSale({ is_available: true, out_of_stock: true })).toBe(false);
    expect(
      isOnSale({ is_available: true, out_of_stock: true, stock_quantity: 40 }),
    ).toBe(false);
  });

  it('is not on sale when there is no dish', () => {
    expect(isOnSale(null)).toBe(false);
    expect(isOnSale(undefined)).toBe(false);
  });
});
