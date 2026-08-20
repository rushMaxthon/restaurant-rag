# Menu Item Customization Flow

## Scope

This flow now covers backend, `frontend-admin`, `frontend-customer`, and `mobile` support for optional menu item sizes and customization groups while keeping the existing simple-item flow backward compatible.

Current scope:

- Backend schema and API support
- Admin/owner menu item modal support
- Customer web menu item selection UI
- Mobile menu item selection UI
- Cart payload expansion
- Offer preview pricing with custom selections
- Order item customization persistence and snapshot storage
- UUID-based customization entities
- Option-level `is_countable` support

Not included yet:

- Customer-facing post-add edit flow inside cart
- Owner/admin analytics broken down by selected size or options
- Recommendation/chat responses that proactively describe available customizations before detail is opened

## Data Model

### `menu_items`

Existing table remains the parent record for every menu item.

New additive fields:

- `has_sizes: boolean`
- `has_customizations: boolean`

Compatibility rule:

- `price` still exists and remains required
- for sized items, `price` is automatically synced to the lowest active size price
- existing menu items with no sizes/customizations continue working unchanged

### `menu_item_sizes`

Each row belongs to one menu item.

Fields:

- `id: UUID`
- `menu_item_id: UUID`
- `name: string`
- `price: decimal`
- `is_active: boolean`
- `sort_order: integer`

### `menu_item_customization_groups`

Each group belongs to one menu item and can optionally belong to one size.

Fields:

- `id: UUID`
- `menu_item_id: UUID`
- `menu_item_size_id: UUID | null`
- `title: string`
- `selection_type: SINGLE | MULTI`
- `is_required: boolean`
- `min_selection: integer`
- `max_selection: integer`
- `is_active: boolean`
- `sort_order: integer`

Rules:

- `menu_item_size_id = null` means item-level group
- `menu_item_size_id = <size-id>` means size-specific group
- when admin selects the same logical group for multiple sizes, the admin form expands that into one size-linked group per selected size at save time
- this keeps storage backward compatible while still making the size-to-group mapping explicit in the backend

### `menu_item_customization_options`

Each option belongs to one customization group.

Fields:

- `id: UUID`
- `group_id: UUID`
- `name: string`
- `extra_price: decimal`
- `is_active: boolean`
- `is_countable: boolean`
- `sort_order: integer`

`is_countable` behavior:

- `true`: future customer/cart flows may store quantity per option
- `false`: option behaves like a normal selected/unselected addon

## Relationships

```text
MenuItem
  -> MenuItemSize[]
  -> MenuItemCustomizationGroup[] (item-level)

MenuItemSize
  -> MenuItemCustomizationGroup[] (size-specific)

MenuItemCustomizationGroup
  -> MenuItemCustomizationOption[]
```

## API Shape

## Create / Update Request

Old payloads still work.

Simple item:

```json
{
  "restaurant_id": "uuid",
  "restaurant_location_id": "uuid",
  "name": "Margherita Pizza",
  "category": "Pizza",
  "price": 299,
  "is_veg": true,
  "is_available": true,
  "is_new_launch": false,
  "has_sizes": false,
  "has_customizations": false,
  "sizes": [],
  "customization_groups": []
}
```

Sized item:

```json
{
  "restaurant_id": "uuid",
  "restaurant_location_id": "uuid",
  "name": "Margherita Pizza",
  "category": "Pizza",
  "price": 299,
  "is_veg": true,
  "is_available": true,
  "is_new_launch": false,
  "has_sizes": true,
  "has_customizations": false,
  "sizes": [
    {
      "name": "Small",
      "price": 299,
      "is_active": true,
      "sort_order": 0,
      "customization_groups": []
    },
    {
      "name": "Large",
      "price": 499,
      "is_active": true,
      "sort_order": 1,
      "customization_groups": []
    }
  ],
  "customization_groups": []
}
```

Sized item with size-specific customizations:

```json
{
  "restaurant_id": "uuid",
  "restaurant_location_id": "uuid",
  "name": "Margherita Pizza",
  "category": "Pizza",
  "price": 299,
  "is_veg": true,
  "is_available": true,
  "is_new_launch": false,
  "has_sizes": true,
  "has_customizations": true,
  "sizes": [
    {
      "name": "Large",
      "price": 499,
      "is_active": true,
      "sort_order": 2,
      "customization_groups": [
        {
          "title": "Choose Crust",
          "selection_type": "SINGLE",
          "is_required": true,
          "min_selection": 1,
          "max_selection": 1,
          "is_active": true,
          "sort_order": 0,
          "options": [
            {
              "name": "Regular",
              "extra_price": 0,
              "is_active": true,
              "is_countable": false,
              "sort_order": 0
            },
            {
              "name": "Cheese Burst",
              "extra_price": 80,
              "is_active": true,
              "is_countable": false,
              "sort_order": 1
            }
          ]
        },
        {
          "title": "Extra Toppings",
          "selection_type": "MULTI",
          "is_required": false,
          "min_selection": 0,
          "max_selection": 3,
          "is_active": true,
          "sort_order": 1,
          "options": [
            {
              "name": "Extra Cheese",
              "extra_price": 50,
              "is_active": true,
              "is_countable": true,
              "sort_order": 0
            },
            {
              "name": "Jalapeno",
              "extra_price": 30,
              "is_active": true,
              "is_countable": false,
              "sort_order": 1
            }
          ]
        }
      ]
    }
  ],
  "customization_groups": []
}
```

Item-level customization example without sizes:

```json
{
  "name": "Cold Coffee",
  "category": "Beverages",
  "price": 180,
  "is_veg": true,
  "is_available": true,
  "is_new_launch": false,
  "has_sizes": false,
  "has_customizations": true,
  "sizes": [],
  "customization_groups": [
    {
      "title": "Sugar Level",
      "selection_type": "SINGLE",
      "is_required": true,
      "min_selection": 1,
      "max_selection": 1,
      "is_active": true,
      "sort_order": 0,
      "options": [
        {
          "name": "Regular",
          "extra_price": 0,
          "is_active": true,
          "is_countable": false,
          "sort_order": 0
        },
        {
          "name": "Less Sugar",
          "extra_price": 0,
          "is_active": true,
          "is_countable": false,
          "sort_order": 1
        }
      ]
    }
  ]
}
```

## Response Shape

`GET /menu-items` and `GET /menu-items/{id}` now return:

```json
{
  "id": "uuid",
  "restaurant_id": "uuid",
  "restaurant_location_id": "uuid",
  "name": "Margherita Pizza",
  "category": "Pizza",
  "price": 299,
  "has_sizes": true,
  "has_customizations": true,
  "sizes": [
    {
      "id": "uuid",
      "name": "Large",
      "price": 499,
      "is_active": true,
      "sort_order": 2,
      "customization_groups": [
        {
          "id": "uuid",
          "menu_item_size_id": "uuid",
          "title": "Choose Crust",
          "selection_type": "SINGLE",
          "is_required": true,
          "min_selection": 1,
          "max_selection": 1,
          "is_active": true,
          "sort_order": 0,
          "options": [
            {
              "id": "uuid",
              "name": "Regular",
              "extra_price": 0,
              "is_active": true,
              "is_countable": false,
              "sort_order": 0
            }
          ]
        }
      ]
    }
  ],
  "customization_groups": []
}
```

## Validation Rules

Backend and admin form both enforce:

- item name required
- category required
- if `has_sizes = true`, at least one active size is required
- each size needs `name` and `price > 0`
- if `has_customizations = true`, at least one active group is required
- each group needs a title
- each group needs at least one option
- each option needs a name
- `extra_price >= 0`
- `sort_order >= 0`
- `max_selection >= min_selection`
- `selection_type = SINGLE` requires `max_selection = 1`
- required groups must have `min_selection >= 1`

## Backward Compatibility

Existing menu items remain valid because:

- all new fields are additive
- `has_sizes` and `has_customizations` default to `false`
- old create/update payloads can still omit all customization fields
- simple items still use the existing price and add-to-cart flow
- cart/order/payment flows accept old payloads and only expand when size/options are present
- recommendation, offer, chat, and bestseller flows continue reading the existing `menu_items` table

## Pricing Strategy

Current behavior:

```text
no size selected -> menu_items.price
selected size price
+ sum(selected option extra_price)
+ (countable option extra_price * quantity)
= final line item price
```

Example:

```text
Large Pizza = 499
Cheese Burst = 80
Extra Cheese x2 = 50 * 2
Jalapeno = 30

Total = 709
```

## Admin Flow

The existing add/edit menu item modal stays in place.

New modal sections:

- `Has sizes?`
- `Has customizations/toppings?`
- Size list with active/sort order
- Group editor
- Option editor
- `is_countable` checkbox on each option
- `Available for sizes` checkboxes when size management is enabled

Example admin flow with sizes:

```text
Sizes:
- Small
- Medium
- Large

Group:
Choose Crust

Available for sizes:
[ ] Small
[ ] Medium
[x] Large
```

When sizes are enabled:

- groups are created once in the admin form
- each group must select one or more sizes under `Available for sizes`
- on save, the admin form expands each selected size into the existing size-linked backend structure
- when a size is deleted, its group mappings are removed automatically and groups with no remaining sizes are dropped

When sizes are disabled:

- groups are managed at item level

## Customer Cart Payload

Both customer clients now store customized cart lines like:

```json
{
  "menu_item_id": "uuid",
  "menu_item_size_id": "uuid",
  "selected_options": [
    {
      "option_id": "uuid",
      "quantity": 2
    }
  ],
  "quantity": 1
}
```

Client-side cart state also keeps a friendly snapshot for rendering:

```json
{
  "id": "menu-item-id::size-id::option-a:1|option-b:2",
  "menuItem": {},
  "selectedSize": {
    "id": "uuid",
    "name": "Large",
    "price": 499
  },
  "selectedOptions": [
    {
      "groupId": "uuid",
      "groupTitle": "Extra Toppings",
      "selectionType": "MULTI",
      "optionId": "uuid",
      "optionName": "Extra Cheese",
      "extraPrice": 50,
      "quantity": 2,
      "isCountable": true
    }
  ],
  "unitPrice": 709,
  "quantity": 1
}
```

This cart-line `id` makes each size/customization combination independent, so:

- `Large + Cheese Burst` and `Large + Regular Crust` stay as separate lines
- simple items still collapse into one normal line
- quantity updates remain safe after app reload because the line id is restored from saved cart state

## Order Snapshot Payload

Orders now persist snapshots for:

- item name
- selected size name and price
- group titles
- option names
- option quantities
- extra prices

Order responses include:

- `menu_item_size_id`
- `size_name_snapshot`
- `base_unit_price`
- `customization_total_price`
- `selected_options_snapshot`

This keeps historical orders stable even if the menu item later changes.

## Customer UI Behavior

On `frontend-customer` and `mobile`:

- simple items still use the existing add-to-cart flow
- items with sizes show the size selector first
- active item-level groups and active size-level groups are both supported
- `SINGLE` groups behave like radio selection
- `MULTI` groups behave like checkbox selection
- countable options expose quantity controls
- live price updates before add-to-cart
- required groups must be satisfied before add-to-cart
- cart rows display selected size and option summaries
- checkout and personalized-offer preview requests now include size and option payloads
- direct add entry points route customizable items into the detail screen instead of silently adding an incomplete line

## Migration

Run:

```bash
cd backend
alembic upgrade head
```

This creates:

- `menu_item_sizes`
- `menu_item_customization_groups`
- `menu_item_customization_options`
- `menu_item_customization_selection_type` enum
