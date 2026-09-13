# Bangkok Bowl ordering app

## Goal
Build a full-width, mobile-first ordering experience for one Thai restaurant across Navrangpura, Bodakdev, and Vastrapur. All screens use realistic Ahmedabad pricing, responsive layouts from 400–1920px, dark mode, accessible controls, and the supplied white-label color variables.

## What will be built

### Shared experience
- Create an edge-to-edge restaurant shell with responsive desktop navigation, compact mobile navigation, branch selector, cart count, account access, and light/dark theme control.
- Define the requested CSS variable palette at `:root`, add dark equivalents, and map every visual role through semantic theme tokens; component files will contain no literal colors.
- Add shared dish cards, INR formatting from decimal strings, Indian veg/non-veg marks, 44px controls, fixed image ratios, and branded initials placeholders for missing or failed images.
- Model the exact `MenuItem`, `Restaurant`, `RestaurantLocation`, and `Order` field shapes, then provide realistic branch-aware mock data, offers, sample orders, sizes, and add-ons.

### Customer screens
- **Home `/`**: food-photo hero, selected branch/open status, menu search, category rail, popular menu grid, AI concierge promotion, personalized picks, and active offers.
- **Menu `/menu`**: three-branch switcher, sticky category filters, search, availability states, complete dish grid, and fast add controls.
- **Dish `/menu/$itemId`**: large food image, rating when present, prep time, size choice, required/optional single and multi-select add-ons, recommendations, and sticky add-to-cart action.
- **Cart `/cart`**: item imagery and customization summaries, quantity controls, removal, bill breakdown, delivery/pickup toggle, and sticky checkout action.
- **Checkout `/checkout`**: fulfillment details, address or pickup branch, order summary, and a working mock place-order flow.
- **Concierge `/concierge`**: one browser-saved conversation with streamed markdown responses, visible reasoning/loading states, and clickable dish suggestions that add directly to the shared cart.
- **Account `/login` and `/register`**: clean, validated mock authentication forms linked to the ordering flow.
- **Orders `/orders` and `/orders/$orderId`**: order history plus a detailed visual timeline from Placed through Delivered.

### Ordering behavior
- Keep branch, cart, fulfillment choice, theme, mock account state, and the single concierge conversation in browser storage so the prototype survives refreshes without requiring a database.
- Recalculate prices from selected size, add-ons, and quantity; show subtotal, branch delivery fee, tax, discount, and total in ₹.
- Prevent unavailable items from being added, validate required customization groups, and update cart quantities across all screens.
- Use realistic offers and Thai dishes priced ₹60–₹600, including Pad Thai, Tom Yum Goong, Green Curry, Som Tum, Mango Sticky Rice, Massaman Curry, and Thai Iced Tea.

## AI concierge
- Connect the chat to Lovable AI using the default supported OpenAI model through a server-only streaming endpoint; the API key and prompt remain server-side.
- Send the complete browser-stored conversation on each request and render responses with markdown.
- Install and compose the official AI Elements conversation, message, prompt input, and loading primitives, then add Bangkok Bowl dish suggestion cards around them.
- Give the agent a focused Thai-food system prompt with the current branch/menu context and a tool that returns structured menu recommendations; suggestion results remain actionable in chat.
- Surface AI credit, policy, rate-limit, and server errors clearly without unsafe retries.

## Visual direction and assets
- Use a warm, editorial Bangkok street-food direction: vivid orange brand actions, clean white/charcoal surfaces, expressive food photography, compact typography, and restrained shadows.
- Generate and bundle a coherent hero image plus key dish photography rather than hotlinking stock images; other dishes intentionally exercise the branded placeholder system.
- Limit motion to opacity and transform, add subtle entrance/selection feedback, and fully disable nonessential motion for reduced-motion preferences.

## Technical details
- Build with TanStack Start file routes and shared React components; add every referenced route in the same change and define unique metadata per content route.
- Use a typed client store with SSR-safe browser-storage hydration. This is a front-end prototype: login, checkout, and order progression are simulated locally rather than connected to payments, delivery logistics, or a database.
- Use a server route for the streamed concierge request, AI SDK message parts, complete history on every call, and server-side menu tools.
- Add selective unit coverage for currency/cart calculations and use browser checks for desktop/mobile layout, image failure fallbacks, cart/customization flows, order tracking, theme switching, persistence, and chat.

## Validation
- Run lint and the project’s normal build checks.
- Test at 400px, tablet, 1280px, and 1920px widths for full-width composition and overlap-free controls.
- Walk through branch switching, search/filtering, dish customization, cart totals, delivery/pickup, mock checkout, order timeline, login/register validation, theme switching, and refresh persistence.
- Send a real concierge message through the final AI path and verify streamed markdown, a clickable recommendation, add-to-cart, and visible failure handling.
