import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * An owner saving a dish must not break the carts already holding it.
 *
 * Every save used to rebuild the item from the payload: sizes and
 * customization groups cleared, then recreated with fresh UUIDs. Nothing
 * looked different afterwards — same names, same prices — but every id had
 * changed, and a cart holds ids. `resolve_menu_item_selection` refuses ids it
 * cannot find, so a customer who had built an order minutes earlier met "The
 * selected size is unavailable for Build Your Own Pizza" on the last screen
 * before paying, with no way to fix it except deleting the line.
 *
 * This is checked through the API rather than the browser because the ids are
 * the whole subject: the screen looks identical either way, which is exactly
 * why nobody noticed.
 */

const API = "http://127.0.0.1:8000/api";
const ITEM = "07e52a7c-2d32-4414-87cf-f62c0bf9c6ff";

type Fingerprint = { sizes: string[]; groups: string[]; options: string[] };

async function readItem(request: APIRequestContext) {
  return (await request.get(`${API}/menu-items/${ITEM}`)).json();
}

/** Every id a cart could be holding, sorted so order changes do not matter. */
function idsOf(item: Record<string, never>): Fingerprint {
  const sizes = (item.sizes ?? []) as Record<string, never>[];
  const groups = [
    ...((item.customization_groups ?? []) as Record<string, never>[]),
    ...sizes.flatMap((size) => (size.customization_groups ?? []) as Record<string, never>[]),
  ];
  return {
    sizes: sizes.map((size) => size.id as string).sort(),
    groups: groups.map((group) => group.id as string).sort(),
    options: groups
      .flatMap((group) => ((group.options ?? []) as Record<string, never>[]).map((o) => o.id as string))
      .sort(),
  };
}

/** The item put back through the same endpoint the dashboard uses. */
async function save(
  request: APIRequestContext,
  item: Record<string, never>,
  edit: (body: Record<string, never>) => void,
) {
  const auth = await request.post(`${API}/auth/login`, {
    data: { email: "admin@example.com", password: "password123" },
  });
  const { access_token } = await auth.json();

  const group = (g: Record<string, never>) => ({
    title: g.title,
    selection_type: g.selection_type,
    is_required: g.is_required,
    min_selection: g.min_selection,
    max_selection: g.max_selection,
    supports_halves: g.supports_halves,
    is_active: g.is_active,
    sort_order: g.sort_order,
    options: (g.options as Record<string, never>[]).map((o) => ({
      name: o.name,
      extra_price: Number(o.extra_price),
      is_active: o.is_active,
      is_countable: o.is_countable,
      sort_order: o.sort_order,
    })),
  });

  const body = {
    name: item.name,
    category: item.category,
    cuisine_type: item.cuisine_type,
    description: item.description,
    price: Number(item.price),
    is_veg: item.is_veg,
    is_available: item.is_available,
    image_url: item.image_url,
    is_new_launch: item.is_new_launch,
    has_sizes: item.has_sizes,
    has_customizations: item.has_customizations,
    customization_groups: [],
    restaurant_location_id: item.restaurant_location_id,
    sizes: (item.sizes as Record<string, never>[]).map((z) => ({
      name: z.name,
      price: Number(z.price),
      is_active: z.is_active,
      sort_order: z.sort_order,
      customization_groups: (z.customization_groups as Record<string, never>[]).map(group),
    })),
  } as unknown as Record<string, never>;
  edit(body);

  const res = await request.put(`${API}/menu-items/${ITEM}`, {
    headers: { Authorization: `Bearer ${access_token}` },
    data: body,
  });
  expect(res.status(), await res.text()).toBe(200);
}

test.describe("saving a dish keeps the ids customers are holding", () => {
  test("a price change leaves every size, group and option id alone", async ({ request }) => {
    const before = await readItem(request);
    const fingerprint = idsOf(before);
    const original = Number((before.sizes as { price: string }[])[0].price);

    await save(request, before, (body) => {
      const sizes = body.sizes as unknown as { price: number }[];
      sizes[0].price = Number((original + 1).toFixed(2));
    });
    try {
      expect(idsOf(await readItem(request))).toEqual(fingerprint);
    } finally {
      const now = await readItem(request);
      await save(request, now, (body) => {
        const sizes = body.sizes as unknown as { price: number }[];
        sizes[0].price = original;
      });
    }
    // And putting the price back does not churn them either.
    expect(idsOf(await readItem(request))).toEqual(fingerprint);
  });

  test("a topping cap change leaves the option ids alone", async ({ request }) => {
    const before = await readItem(request);
    const fingerprint = idsOf(before);
    const groupOf = (item: Record<string, never>) =>
      (item.sizes as Record<string, never>[])
        .flatMap((z) => (z.customization_groups ?? []) as { title: string; max_selection: number }[])
        .find((g) => g.title === "Toppings");
    const original = groupOf(before)?.max_selection ?? 2;
    const target = original === 1 ? 2 : 1;

    await save(request, before, (body) => {
      for (const size of body.sizes as unknown as { customization_groups: { title: string; max_selection: number }[] }[]) {
        for (const group of size.customization_groups) {
          if (group.title === "Toppings") group.max_selection = target;
        }
      }
    });
    try {
      const after = await readItem(request);
      expect(groupOf(after)?.max_selection).toBe(target);
      expect(idsOf(after)).toEqual(fingerprint);
    } finally {
      const now = await readItem(request);
      await save(request, now, (body) => {
        for (const size of body.sizes as unknown as { customization_groups: { title: string; max_selection: number }[] }[]) {
          for (const group of size.customization_groups) {
            if (group.title === "Toppings") group.max_selection = original;
          }
        }
      });
    }
  });
});
