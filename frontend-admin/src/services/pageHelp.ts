/**
 * The words behind the "i" beside every page title.
 *
 * One list, for the same reason `routes.tsx` is one list: written inside each
 * page, twenty-six explanations drift into twenty-six voices, and nothing can
 * check that a page has one at all. Here a test can read every entry.
 *
 * Three questions per page — what is this, who is it for, what do I do here —
 * because those are the three a new owner asks on their first day, and the
 * line under a page title only ever had room for the first.
 *
 * The panel is one dashboard for two roles, and most pages mean something
 * different to each: an admin watches every restaurant, an owner runs their
 * own. So an answer is either one sentence for both, or one per role. A page
 * only one role can open still answers for both; the test asks every page the
 * same thing and a special case there would be a hole in it.
 */
import type { UserRole } from "../types/app";

type PerRole = string | { ADMIN: string; OWNER: string };

interface PageHelpEntry {
  title: string;
  what: PerRole;
  who: PerRole;
  action: PerRole;
}

export interface PageHelpCopy {
  title: string;
  what: string;
  who: string;
  action: string;
}

const ADMIN_ONLY = "The platform admin only. Restaurant owners do not see this page.";

export const PAGE_HELP = {
  dashboard: {
    title: "Dashboard",
    what: {
      ADMIN: "Today's numbers for the whole platform: orders, revenue and AI chat activity across every restaurant.",
      OWNER: "Today's numbers for your restaurant: orders, revenue, how the menu is doing and your top dishes.",
    },
    who: {
      ADMIN: "The platform admin, as the first look of the day.",
      OWNER: "You, as the first look of the day.",
    },
    action: "Read it top to bottom and press Refresh for the latest figures. To act on something, open its own page from the menu on the left.",
  },
  reports: {
    title: "Reports",
    what: {
      ADMIN: "Revenue, orders, customer engagement and AI activity over a period you choose, across every restaurant.",
      OWNER: "Revenue, order flow, best-selling dishes and AI activity for your restaurant over a period you choose.",
    },
    who: {
      ADMIN: "The platform admin, to compare restaurants and spot trends.",
      OWNER: "You, to see how the business is doing over days and weeks rather than today.",
    },
    action: "Pick the period at the top, then read the charts. Nothing here changes anything, so it is safe to explore.",
  },
  "ai-manager": {
    title: "AI Manager",
    what: "An assistant that has read the restaurant's own orders and menu. It opens with a briefing and answers questions in plain language.",
    who: {
      ADMIN: "The platform admin, looking at one restaurant at a time. Pick the restaurant at the top first.",
      OWNER: "You. It only ever reads your own restaurant's data.",
    },
    action: "Read the briefing, then type a question such as \"which dishes sold less this week?\". It suggests; it never changes anything without your approval.",
  },
  restaurants: {
    title: "Restaurants",
    what: {
      ADMIN: "Every restaurant on the platform, with its approval state and owner.",
      OWNER: "Your restaurant's profile: its name, details and settings.",
    },
    who: {
      ADMIN: "The platform admin, who onboards and approves restaurants.",
      OWNER: "You, as the owner of this restaurant.",
    },
    action: {
      ADMIN: "Search or filter the list, add a new restaurant, approve a pending one, or open a restaurant to manage it.",
      OWNER: "Open your restaurant to check its details, then go to its branches for menus, hours and orders.",
    },
  },
  "restaurant-detail": {
    title: "Restaurant workspace",
    what: "Everything about one restaurant in one place: its profile, settings, menu and recent orders.",
    who: {
      ADMIN: "The platform admin, reviewing or fixing one restaurant.",
      OWNER: "You. This is your restaurant's home page in the panel.",
    },
    action: "Edit the profile and settings here. For anything that belongs to one branch, such as hours, prices or delivery, open that branch.",
  },
  locations: {
    title: "Locations",
    what: "The branches of this restaurant. Customers order from a branch, so each one has its own menu, hours and orders.",
    who: {
      ADMIN: "The platform admin, for the restaurant picked at the top.",
      OWNER: "You, for your own branches.",
    },
    action: "Add a branch, or open one to manage its settings, time slots, menu and orders.",
  },
  "location-detail": {
    title: "Branch workspace",
    what: "One branch: its address and hours, delivery and pickup settings, time slots, menu and orders.",
    who: {
      ADMIN: "The platform admin and the restaurant's owner. Only the admin can change the commission.",
      OWNER: "You and the platform admin. This is where your branch is set up.",
    },
    action: {
      ADMIN: "Change settings and press Save. Changing the commission re-prices every menu item at this branch straight away.",
      OWNER: "Change settings and press Save. The commission is set by the platform, so you can see it here but not change it.",
    },
  },
  "menu-items": {
    title: "Menu items",
    what: {
      ADMIN: "Every dish on the platform, across every restaurant and branch.",
      OWNER: "Every dish your restaurant sells, at every branch.",
    },
    who: {
      ADMIN: "The platform admin, to check or correct any restaurant's menu.",
      OWNER: "You, or whoever keeps your menu up to date.",
    },
    action: "Search or filter to find a dish, then open it to change its price, photo, sizes, options or whether customers can see it. Use Add to create a new one.",
  },
  "menu-item-editor": {
    title: "Menu item editor",
    what: "The form for one dish: name, description, photo, price, sizes and the choices a customer can make.",
    who: "Whoever manages the menu: the owner, or the platform admin on their behalf.",
    action: "Fill in the form and press Save. Type your own price: the platform commission is added on top of it when the dish is saved.",
  },
  orders: {
    title: "Orders",
    what: {
      ADMIN: "The full list of orders across every restaurant, past and present.",
      OWNER: "The full list of orders for your restaurant, past and present.",
    },
    who: {
      ADMIN: "The platform admin, to look up any order.",
      OWNER: "You and your staff, to look up any order.",
    },
    action: "Search or filter to find an order, then open it for its bill, payment, history and delivery. For what is happening right now, use Live orders.",
  },
  "order-detail": {
    title: "Order",
    what: "One order from start to finish: the items, the bill, the payment, each step it went through and its delivery.",
    who: {
      ADMIN: "The platform admin, usually when a restaurant or customer asks about an order.",
      OWNER: "You and your staff, when a customer asks about their order.",
    },
    action: "Read the timeline to see where the order is. The button at the top moves it to its next step, such as accepting it or handing it to the rider.",
  },
  "kitchen-staff": {
    title: "Kitchen staff",
    what: "The logins for the kitchen order board. Each one opens the board for one branch, or for every branch of one restaurant.",
    who: {
      ADMIN: "The platform admin, for the restaurant picked at the top.",
      OWNER: "You. Give each kitchen screen its own login rather than sharing yours.",
    },
    action: "Add a login, rename it, move it to another branch, or deactivate it when somebody leaves. A login cannot be deleted, so its order history stays intact.",
  },
  offers: {
    title: "Offers",
    what: "Discounts and deals customers see in the app, including the ones the AI suggests.",
    who: {
      ADMIN: "The platform admin, running offers for any restaurant or branch.",
      OWNER: "You, running offers for your own restaurant.",
    },
    action: "Create an offer, set what it gives and when it runs, then make it active. Pause one to stop it for a while. AI-suggested offers are listed here too and can be edited.",
  },
  marketing: {
    title: "Marketing Hub",
    what: "Campaigns sent to customers, such as a push notification or a WhatsApp message, and what each one earned.",
    who: {
      ADMIN: "The platform admin, for the restaurant picked at the top.",
      OWNER: "You, to bring customers back and see what worked.",
    },
    action: "Press Create campaign and answer six short questions. Open a past campaign to see who it reached and the orders that followed.",
  },
  "campaign-editor": {
    title: "Create campaign",
    what: "Builds one campaign in six steps: where it goes, why, who gets it, the words, when it is sent, and a final check.",
    who: "The owner, or the platform admin on their behalf.",
    action: "Answer each step and press Next. You can save a draft at any point. Nothing reaches a customer until you press send on the last step.",
  },
  "campaign-detail": {
    title: "Campaign",
    what: "One campaign: what was sent, who it was sent to, and the orders that came in afterwards.",
    who: "The owner, or the platform admin, checking how a campaign did.",
    action: "Read the results. A draft or scheduled campaign can still be edited, a scheduled one can be cancelled, and any campaign can be duplicated to run again.",
  },
  channels: {
    title: "Channels",
    what: "The places a campaign can be sent from: push, WhatsApp, SMS, email and social accounts.",
    who: {
      ADMIN: "The platform admin, for the restaurant picked at the top.",
      OWNER: "You. Each channel is linked to an account you already have with that provider.",
    },
    action: "Push works out of the box. Connect any other channel once with its account details, and it stays connected.",
  },
  "generated-combos": {
    title: "Combo suggestions",
    what: "Meal combos the system builds from dishes customers really do order together.",
    who: {
      ADMIN: "The platform admin, who can also rebuild the suggestions.",
      OWNER: "You, to decide which combos your customers see.",
    },
    action: "Open a combo to see what is in it and why it was suggested. Move it to Live so customers see it, or archive it to take it away.",
  },
  users: {
    title: "Users",
    what: {
      ADMIN: "Every account on the platform: admins, owners, kitchen logins and customers.",
      OWNER: "The customers who signed up in your restaurant's app.",
    },
    who: {
      ADMIN: "The platform admin, who controls who can sign in.",
      OWNER: "You, to see who your customers are.",
    },
    action: {
      ADMIN: "Search or filter by role, and deactivate an account to sign it out and stop it signing in. Activate it again to restore access.",
      OWNER: "Search the list to find a customer. To send them something, use the Marketing Hub.",
    },
  },
  preferences: {
    title: "Taste questions",
    what: "The short questions a customer answers when they first open the app, used to recommend dishes they will like.",
    who: {
      ADMIN: "The platform admin, who writes the questions every restaurant's app asks.",
      OWNER: "You. Platform questions can be hidden for your app but not reworded.",
    },
    action: {
      ADMIN: "Add, edit or reorder a question with the arrows. Changes reach customers straight away, with no app update.",
      OWNER: "Hide a platform question you do not want, and add, edit or reorder your own. Changes reach customers straight away.",
    },
  },
  website: {
    title: "Storefront content",
    what: "The words on the restaurant's own site: its headline, its description and what a search result shows.",
    who: {
      ADMIN: "The platform admin, editing on behalf of the restaurant picked at the top.",
      OWNER: "You. These are your words, shown to your customers.",
    },
    action: "Type the text and press Save. A field left empty is either filled from the restaurant's name and city, or simply not shown.",
  },
  branding: {
    title: "Branding",
    what: "The colour and look of your customer app and site. Menus, prices and order statuses keep their own colours.",
    who: "The restaurant's owner. Each restaurant chooses its own look.",
    action: "Pick a preset colour or enter your own, check it in the phone preview, and press Save.",
  },
  tenants: {
    title: "Tenants",
    what: "Every restaurant's own app and site on the platform: whether it is live, what it carries and whether it is answering.",
    who: ADMIN_ONLY,
    action: "Filter by state and open a restaurant to manage it. A storefront can be suspended, offboarded or restored from its row, each with a reason.",
  },
  "ai-logs": {
    title: "AI logs",
    what: "A record of what customers asked the food chat, what it found on the menu and what it answered.",
    who: ADMIN_ONLY,
    action: "Open a trace to check that an answer was sensible. Use it to investigate a complaint about the chat; nothing here can be edited.",
  },
  notifications: {
    title: "Notification Center",
    what: "Sends a push notification from the platform itself to customers' phones, and lists what was sent recently.",
    who: ADMIN_ONLY,
    action: "Write the title and message, choose who receives it and press Send. It cannot be recalled, so read it twice first.",
  },
  settings: {
    title: "Settings",
    what: "Your own account details, and how this panel looks on this browser, such as light or dark mode.",
    who: "Whoever is signed in. These choices affect only you, on this device.",
    action: "Change a preference and it applies at once. Nothing here affects customers or other staff.",
  },
} satisfies Record<string, PageHelpEntry>;

export type PageHelpId = keyof typeof PAGE_HELP;

function forRole(value: PerRole, role: UserRole): string {
  if (typeof value === "string") return value;
  // Only ADMIN and OWNER can open the panel. Anything else reads the owner's
  // words: they describe one restaurant, which is the narrower claim.
  return role === "ADMIN" ? value.ADMIN : value.OWNER;
}

export function pageHelp(id: PageHelpId, role: UserRole): PageHelpCopy {
  const entry: PageHelpEntry = PAGE_HELP[id];
  return {
    title: entry.title,
    what: forRole(entry.what, role),
    who: forRole(entry.who, role),
    action: forRole(entry.action, role),
  };
}
