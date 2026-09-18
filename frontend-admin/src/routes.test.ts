/**
 * The route table is the one place that decides who can see what.
 *
 * Before it existed the same decision was made in four places — a nested
 * ternary, an allowlist map, and two `Set`s in the sidebar — and they had
 * already drifted apart. These tests pin the drift shut: the navigation and
 * the permission check are the same list now, and the assertions below fail
 * if anyone splits them again.
 */

import { describe, expect, it } from "vitest";

import {
  ROUTES,
  activeNavPathFor,
  defaultPathFor,
  matchRoute,
  mayOpen,
  navFor,
  redirectFor,
} from "./routes";
import type { UserRole } from "./types/app";

const OWNER_RESTAURANT = "restaurant-of-the-owner";
const SOMEONE_ELSE = "restaurant-of-somebody-else";

function paths(role: UserRole): string[] {
  return navFor(role).flatMap((section) => section.items.map((item) => item.path));
}

describe("the navigation and the permission check are the same list", () => {
  it("offers an admin nothing they are not allowed to open", () => {
    for (const path of paths("ADMIN")) {
      const found = matchRoute(path);
      expect(found, path).not.toBeNull();
      expect(mayOpen(found!.route, "ADMIN"), path).toBe(true);
    }
  });

  it("offers an owner nothing they are not allowed to open", () => {
    for (const path of paths("OWNER")) {
      const found = matchRoute(path);
      expect(found, path).not.toBeNull();
      expect(mayOpen(found!.route, "OWNER"), path).toBe(true);
    }
  });

  it("hides nothing a role can reach by typing the address", () => {
    // The bug this replaces: an administrator was allowed to open Menu Items
    // and Generated Combos, and the sidebar never offered either.
    for (const role of ["ADMIN", "OWNER"] as UserRole[]) {
      const offered = new Set(paths(role));
      const reachable = ROUTES.filter(
        (route) => route.nav && mayOpen(route, role),
      ).map((route) => route.pattern);
      for (const pattern of reachable) {
        expect(offered.has(pattern), `${role} cannot see ${pattern}`).toBe(true);
      }
    }
  });

  it("names the owner's single restaurant for what it is", () => {
    const ownerLabels = navFor("OWNER").flatMap((section) =>
      section.items.map((item) => item.label),
    );
    const adminLabels = navFor("ADMIN").flatMap((section) =>
      section.items.map((item) => item.label),
    );
    expect(ownerLabels).toContain("My Restaurant");
    expect(adminLabels).toContain("Restaurants");
  });

  it("keeps platform-only tools away from owners", () => {
    expect(paths("OWNER")).not.toContain("/ai-logs");
    expect(paths("OWNER")).not.toContain("/notifications");
    expect(paths("ADMIN")).not.toContain("/branding");
  });
});

describe("matching an address", () => {
  it("reads the parameters out of the address", () => {
    const found = matchRoute("/admin/restaurants/r1/locations/l1");
    expect(found?.route.id).toBe("location-detail");
    expect(found?.params).toEqual({ restaurantId: "r1", locationId: "l1" });
  });

  it("prefers the longer address when two could match", () => {
    // "/admin/restaurants/r1/locations/l1/menu-items/create" must not be
    // read as a location whose id is "l1/menu-items/create", nor as a
    // location detail page at all.
    expect(matchRoute("/admin/restaurants/r1/locations/l1/menu-items/create")?.route.id).toBe(
      "menu-item-editor-create-under-location",
    );
    expect(matchRoute("/admin/restaurants/r1/locations/l1/menu-items/m1/edit")?.route.id).toBe(
      "menu-item-editor-edit",
    );
    expect(matchRoute("/admin/restaurants/r1/menu-items/create")?.route.id).toBe(
      "menu-item-editor-create",
    );
  });

  it("does not let a parameter swallow a slash", () => {
    expect(matchRoute("/orders/a/b")).toBeNull();
  });

  it("returns nothing for an address that does not exist", () => {
    expect(matchRoute("/nowhere")).toBeNull();
  });

  it("has no two routes claiming the same address", () => {
    const seen = new Set<string>();
    for (const route of ROUTES) {
      expect(seen.has(route.pattern), route.pattern).toBe(false);
      seen.add(route.pattern);
    }
  });
});

describe("where an address sends you instead", () => {
  it("leaves a page you are allowed to see alone", () => {
    expect(redirectFor("/dashboard", "ADMIN", null)).toBeNull();
    expect(redirectFor("/orders/order-1", "ADMIN", null)).toBeNull();
  });

  it("sends an owner back to their own restaurant, not somebody else's", () => {
    // One rule where there used to be five near-identical checks.
    for (const address of [
      `/admin/restaurants/${SOMEONE_ELSE}`,
      `/admin/restaurants/${SOMEONE_ELSE}/locations`,
      `/admin/restaurants/${SOMEONE_ELSE}/locations/l1`,
      `/admin/restaurants/${SOMEONE_ELSE}/menu-items/create`,
      `/admin/restaurants/${SOMEONE_ELSE}/locations/l1/menu-items/m1/edit`,
    ]) {
      expect(redirectFor(address, "OWNER", OWNER_RESTAURANT), address).toBe(
        `/admin/restaurants/${OWNER_RESTAURANT}/locations`,
      );
    }
  });

  it("lets an owner open their own restaurant's pages", () => {
    expect(
      redirectFor(`/admin/restaurants/${OWNER_RESTAURANT}/locations/l1`, "OWNER", OWNER_RESTAURANT),
    ).toBeNull();
  });

  it("turns an owner's all-restaurants into their own branches", () => {
    expect(redirectFor("/restaurants", "OWNER", OWNER_RESTAURANT)).toBe(
      `/admin/restaurants/${OWNER_RESTAURANT}/locations`,
    );
    expect(redirectFor("/restaurants", "ADMIN", null)).toBeNull();
  });

  it("still honours addresses that moved", () => {
    // They are in browser histories and in links people have sent.
    expect(redirectFor("/locations/r1/l1", "ADMIN", null)).toBe(
      "/admin/restaurants/r1/locations/l1",
    );
    expect(redirectFor("/locations", "ADMIN", null)).toBe("/restaurants");
    expect(redirectFor("/locations", "OWNER", OWNER_RESTAURANT)).toBe(
      `/admin/restaurants/${OWNER_RESTAURANT}/locations`,
    );
  });

  it("sends an unknown address home", () => {
    expect(redirectFor("/nowhere", "ADMIN", null)).toBe("/dashboard");
    expect(redirectFor("/nowhere", "OWNER", OWNER_RESTAURANT)).toBe(
      `/admin/restaurants/${OWNER_RESTAURANT}/locations`,
    );
  });

  it("sends a role somewhere it may not go home", () => {
    expect(redirectFor("/ai-logs", "OWNER", OWNER_RESTAURANT)).toBe(
      `/admin/restaurants/${OWNER_RESTAURANT}/locations`,
    );
    expect(redirectFor("/branding", "ADMIN", null)).toBe("/dashboard");
    // App identity is platform configuration, not an owner's to edit.
    expect(redirectFor(`/admin/restaurants/${OWNER_RESTAURANT}/app-client`, "OWNER", OWNER_RESTAURANT)).toBe(
      `/admin/restaurants/${OWNER_RESTAURANT}/locations`,
    );
  });

  it("knows where each role lives", () => {
    expect(defaultPathFor("ADMIN", null)).toBe("/dashboard");
    expect(defaultPathFor("OWNER", OWNER_RESTAURANT)).toBe(
      `/admin/restaurants/${OWNER_RESTAURANT}/locations`,
    );
    expect(defaultPathFor("CUSTOMER", null)).toBe("/login");
  });
});

describe("which sidebar entry looks selected", () => {
  it("keeps a section lit on a page reached from inside it", () => {
    expect(activeNavPathFor("/orders/order-1")).toBe("/orders");
    expect(activeNavPathFor("/admin/restaurants/r1")).toBe("/restaurants");
    expect(activeNavPathFor("/admin/restaurants/r1/locations/l1")).toBe("/restaurants");
    expect(activeNavPathFor("/admin/restaurants/r1/locations/l1/menu-items/m1/edit")).toBe(
      "/restaurants",
    );
  });

  it("lights its own entry for a plain page", () => {
    expect(activeNavPathFor("/reports")).toBe("/reports");
  });
});
