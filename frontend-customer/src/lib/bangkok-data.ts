export type Money = string;
export type MenuSize = { id: string; name: string; price: Money; is_active: boolean };
export type CustomizationOption = { id: string; name: string; extra_price: Money; is_countable: boolean };
export type CustomizationGroup = { id: string; title: string; selection_type: "SINGLE" | "MULTI"; is_required: boolean; min_selection: number; max_selection: number; options: CustomizationOption[] };
export type MenuItem = { id: string; restaurant_id: string; restaurant_location_id: string; name: string; category: string; cuisine_type: string; description: string; price: Money; is_veg: boolean; is_available: boolean; is_bestseller: boolean; image_url: string | null; rating: Money | null; rating_count: number; is_new: boolean; is_favorite: boolean; has_sizes: boolean; has_customizations: boolean; sizes: MenuSize[]; customization_groups: CustomizationGroup[] };
export type RestaurantLocation = { id: string; branch_name: string; address_line_1: string; city: string; delivery_fee: Money; minimum_order_amount: Money; estimated_delivery_time: string | number; estimated_pickup_time: string | number; delivery_enabled: boolean; pickup_enabled: boolean; is_open: boolean; is_active: boolean };
export type Restaurant = { id: string; name: string; slug: string; description: string; cuisine_type: string; city: string; minimum_order_amount: Money; delivery_fee: Money; logo_image_url: string | null; cover_image_url: string | null; is_open: boolean; locations?: RestaurantLocation[] };
export type Order = { id: string; order_number: string; status: string; payment_status: string; fulfillment_type: string; subtotal: Money; delivery_fee: Money; tax_amount: Money; discount_amount: Money; total_amount: Money; placed_at: string; delivery_address: string | null; items: { id: string; item_name_snapshot: string; quantity: number; unit_price: Money; total_price: Money }[] };

export const formatINR = (value: Money | number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(Number(value));

/** Derives the "All" + unique category list from a live menu-items response. */
export const deriveCategories = (items: MenuItem[]) => ["All", ...Array.from(new Set(items.map((item) => item.category)))];
