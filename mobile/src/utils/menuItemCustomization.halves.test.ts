import type {
  CartSelectedOption,
  MenuItem,
  MenuItemCustomizationGroup,
} from '@/types/app';
import {
  buildLineItemId,
  calculateUnitPrice,
  chargedExtraPrice,
  formatCustomizationSummary,
  getSideCounts,
  groupSupportsHalves,
  missingHalf,
  nextSideFor,
  regroupForMode,
  roomOnSide,
  splitSummary,
  validateCustomizationSelection,
} from './menuItemCustomization';

/**
 * Half-and-half, held to the same answers as the web app and the server.
 *
 * Mirrors `frontend-customer/src/lib/customization.test.ts`. Where a number
 * here disagrees with one there, the customer sees one price and is charged
 * another — which is the whole reason these rules are duplicated rather than
 * re-invented.
 */

function group(
  over: Partial<MenuItemCustomizationGroup> = {},
): MenuItemCustomizationGroup {
  return {
    id: 'toppings',
    menu_item_size_id: null,
    title: 'Toppings',
    selection_type: 'MULTI',
    is_required: false,
    min_selection: 0,
    max_selection: 2,
    supports_halves: true,
    is_active: true,
    sort_order: 0,
    options: [
      {
        id: 'pepperoni',
        name: 'Pepperoni',
        extra_price: 50,
        is_active: true,
        is_countable: false,
        sort_order: 0,
      },
      {
        id: 'mushroom',
        name: 'Mushroom',
        extra_price: 30,
        is_active: true,
        is_countable: false,
        sort_order: 1,
      },
    ],
    ...over,
  };
}

function item(over: Partial<MenuItem> = {}): MenuItem {
  return {
    id: 'pizza',
    restaurant_id: 'r1',
    restaurant_location_id: 'l1',
    name: 'Pizza',
    category: 'Pizza',
    price: 200,
    has_sizes: false,
    has_customizations: true,
    sizes: [],
    customization_groups: [group()],
    ...over,
  } as MenuItem;
}

function chose(
  optionId: string,
  portion: CartSelectedOption['portion'],
  over: Partial<CartSelectedOption> = {},
): CartSelectedOption {
  const source = group().options.find(o => o.id === optionId)!;
  return {
    groupId: 'toppings',
    groupTitle: 'Toppings',
    selectionType: 'MULTI',
    optionId: source.id,
    optionName: source.name,
    extraPrice: source.extra_price,
    quantity: 1,
    isCountable: false,
    portion,
    ...over,
  };
}

describe('groupSupportsHalves', () => {
  it('needs the owner flag', () => {
    expect(groupSupportsHalves(group({ supports_halves: false }))).toBe(false);
    expect(groupSupportsHalves(group())).toBe(true);
  });

  it('never splits a single-choice group', () => {
    expect(groupSupportsHalves(group({ selection_type: 'SINGLE' }))).toBe(
      false,
    );
  });
});

describe('chargedExtraPrice', () => {
  it('charges full price for a whole topping', () => {
    expect(chargedExtraPrice(group(), 50, 'WHOLE')).toBe(50);
  });

  it('charges half for half', () => {
    expect(chargedExtraPrice(group(), 50, 'LEFT')).toBe(25);
    expect(chargedExtraPrice(group(), 50, 'RIGHT')).toBe(25);
  });

  it('rounds a half the way the server does', () => {
    expect(chargedExtraPrice(group(), 25.01, 'LEFT')).toBe(12.51);
  });

  it('ignores a portion on a group that cannot be split', () => {
    expect(
      chargedExtraPrice(group({ supports_halves: false }), 50, 'LEFT'),
    ).toBe(50);
  });
});

describe('calculateUnitPrice', () => {
  it('prices two different halves independently', () => {
    const price = calculateUnitPrice({
      menuItem: item(),
      selectedSize: null,
      selectedOptions: [chose('pepperoni', 'LEFT'), chose('mushroom', 'RIGHT')],
    });
    // 200 base + 25 (half pepperoni) + 15 (half mushroom)
    expect(price).toBe(240);
  });

  it('still replaces the base price with the size price', () => {
    const sized = item({
      has_sizes: true,
      sizes: [
        {
          id: 'large',
          name: 'Large',
          price: 300,
          is_active: true,
          sort_order: 0,
          customization_groups: [group()],
        },
      ],
      customization_groups: [],
    });
    const price = calculateUnitPrice({
      menuItem: sized,
      selectedSize: { id: 'large', name: 'Large', price: 300 },
      selectedOptions: [chose('pepperoni', 'LEFT'), chose('mushroom', 'RIGHT')],
    });
    expect(price).toBe(340);
  });

  it('does not halve a topping whose group the owner stopped splitting', () => {
    const narrowed = item({
      customization_groups: [group({ supports_halves: false })],
    });
    const price = calculateUnitPrice({
      menuItem: narrowed,
      selectedSize: null,
      selectedOptions: [chose('pepperoni', 'LEFT')],
    });
    expect(price).toBe(250);
  });
});

describe('buildLineItemId', () => {
  it('keeps half and whole apart', () => {
    const half = buildLineItemId({
      menuItemId: 'pizza',
      selectedSizeId: null,
      selectedOptions: [chose('pepperoni', 'LEFT')],
    });
    const whole = buildLineItemId({
      menuItemId: 'pizza',
      selectedSizeId: null,
      selectedOptions: [chose('pepperoni', 'WHOLE')],
    });
    expect(half).not.toBe(whole);
  });

  it('gives a whole-item line the same id it had before halves existed', () => {
    const withPortion = buildLineItemId({
      menuItemId: 'pizza',
      selectedSizeId: null,
      selectedOptions: [chose('pepperoni', 'WHOLE')],
    });
    const legacy = buildLineItemId({
      menuItemId: 'pizza',
      selectedSizeId: null,
      selectedOptions: [chose('pepperoni', undefined)],
    });
    expect(withPortion).toBe(legacy);
    expect(withPortion).toBe('pizza::default::pepperoni:1');
  });
});

describe('sides', () => {
  it('counts what sits on each half', () => {
    const counts = getSideCounts([
      chose('pepperoni', 'LEFT'),
      chose('mushroom', 'RIGHT'),
    ]);
    expect(counts).toEqual({ LEFT: 1, RIGHT: 1, WHOLE: 0 });
  });

  it('counts the maximum on each half, not across the pair', () => {
    const counts = getSideCounts([chose('pepperoni', 'LEFT')]);
    expect(roomOnSide(group({ max_selection: 1 }), counts, 'LEFT')).toBe(false);
    expect(roomOnSide(group({ max_selection: 1 }), counts, 'RIGHT')).toBe(true);
  });

  it('fills the bare half first', () => {
    expect(nextSideFor(group(), [chose('pepperoni', 'LEFT')])).toBe('RIGHT');
    expect(nextSideFor(group(), [chose('pepperoni', 'RIGHT')])).toBe('LEFT');
  });

  it('skips a side that is already full', () => {
    const capped = group({ max_selection: 1 });
    expect(
      nextSideFor(capped, [
        chose('pepperoni', 'LEFT'),
        chose('mushroom', 'RIGHT'),
      ]),
    ).toBe('LEFT');
  });

  it('names the half that was left undescribed', () => {
    expect(missingHalf([chose('pepperoni', 'LEFT')])).toBe('right');
    expect(missingHalf([chose('pepperoni', 'RIGHT')])).toBe('left');
    expect(
      missingHalf([chose('pepperoni', 'LEFT'), chose('mushroom', 'RIGHT')]),
    ).toBeNull();
    expect(missingHalf([chose('pepperoni', 'WHOLE')])).toBeNull();
  });
});

describe('regroupForMode', () => {
  it('re-rations choices against the cap when leaving split mode', () => {
    const capped = group({ max_selection: 1 });
    const out = regroupForMode(
      capped,
      [chose('pepperoni', 'LEFT'), chose('mushroom', 'RIGHT')],
      false,
    );
    // Two toppings on opposite halves are not two toppings on the whole item.
    expect(out).toHaveLength(1);
    expect(out[0].portion).toBe('WHOLE');
  });

  it('fills left before right when entering split mode', () => {
    const out = regroupForMode(
      group({ max_selection: 1 }),
      [chose('pepperoni', 'WHOLE'), chose('mushroom', 'WHOLE')],
      true,
    );
    expect(out.map(o => o.portion)).toEqual(['LEFT', 'RIGHT']);
  });
});

describe('splitSummary', () => {
  it('reads the item back as two halves', () => {
    const out = splitSummary([
      chose('pepperoni', 'LEFT'),
      chose('mushroom', 'RIGHT'),
    ]);
    expect(out).toEqual({
      left: ['Pepperoni'],
      right: ['Mushroom'],
      whole: [],
    });
  });

  it('keeps a whole topping out of both halves', () => {
    const out = splitSummary([chose('pepperoni', 'WHOLE')]);
    expect(out.left).toEqual([]);
    expect(out.right).toEqual([]);
    expect(out.whole).toEqual(['Pepperoni']);
  });
});

describe('formatCustomizationSummary', () => {
  it('says which half a topping is on', () => {
    expect(
      formatCustomizationSummary(null, [
        chose('pepperoni', 'LEFT'),
        chose('mushroom', 'RIGHT'),
      ]),
    ).toEqual(['Pepperoni · left half', 'Mushroom · right half']);
  });

  it('leaves a whole topping unlabelled', () => {
    expect(
      formatCustomizationSummary(null, [chose('pepperoni', 'WHOLE')]),
    ).toEqual(['Pepperoni']);
  });
});

describe('validateCustomizationSelection', () => {
  const ok = (selectedOptions: CartSelectedOption[], menuItem = item()) =>
    validateCustomizationSelection({
      menuItem,
      selectedSize: null,
      selectedOptions,
    });

  it('accepts a proper half and half', () => {
    expect(
      ok([chose('pepperoni', 'LEFT'), chose('mushroom', 'RIGHT')]),
    ).toBeNull();
  });

  it('refuses a lone half', () => {
    expect(ok([chose('pepperoni', 'LEFT')])).toMatch(/right half/);
  });

  it('refuses split and whole in the same group', () => {
    expect(
      ok([
        chose('pepperoni', 'LEFT'),
        chose('mushroom', 'RIGHT'),
        chose('pepperoni', 'WHOLE', { optionId: 'extra', optionName: 'Extra' }),
      ]),
    ).toMatch(/not both/);
  });

  it('refuses a half on a group the owner cannot split', () => {
    const narrowed = item({
      customization_groups: [group({ supports_halves: false })],
    });
    expect(
      ok([chose('pepperoni', 'LEFT'), chose('mushroom', 'RIGHT')], narrowed),
    ).toMatch(/cannot be applied to half/);
  });

  it('counts the maximum on each half rather than across both', () => {
    const capped = item({
      customization_groups: [group({ max_selection: 1 })],
    });
    // One per side is fine under a cap of one; the old rule called this two.
    expect(
      ok([chose('pepperoni', 'LEFT'), chose('mushroom', 'RIGHT')], capped),
    ).toBeNull();
  });

  it('still refuses too many on one half', () => {
    const capped = item({
      customization_groups: [group({ max_selection: 1 })],
    });
    expect(
      ok(
        [
          chose('pepperoni', 'LEFT'),
          chose('mushroom', 'LEFT'),
          chose('pepperoni', 'RIGHT', {
            optionId: 'extra',
            optionName: 'Extra',
          }),
        ],
        capped,
      ),
    ).toMatch(/at most 1 on each half/);
  });
});
