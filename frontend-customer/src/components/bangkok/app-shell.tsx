import { Link } from "@tanstack/react-router";
import {
  Moon,
  ReceiptText,
  ShoppingBag,
  Sparkles,
  Sun,
  UserRound,
  UtensilsCrossed,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { BranchPicker } from "./branch-picker";
import { useBangkokStore } from "@/lib/bangkok-store";
import { BranchGate } from "@/components/bangkok/branch-gate";
import { useAuth } from "@/lib/auth";
export function AppShell({ children }: { children: React.ReactNode }) {
  const store = useBangkokStore();
  const { isAuthenticated } = useAuth();
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Before the header and everything under it: the branch decides what the
          menu, the concierge and the cart are even talking about. */}
      <BranchGate />
      <header className="site-header sticky top-0 z-50 border-b border-border bg-surface/95 backdrop-blur">
        <div className="flex min-h-16 w-full items-center gap-3 px-4 sm:px-6 lg:px-10">
          <Link to="/" className="mr-auto flex items-center gap-2" aria-label="Bangkok Bowl home">
            <span className="brand-mark">BB</span>
            <span className="brand-name font-display text-xl font-black">
              {store.restaurantName ?? "Bangkok Bowl"}
            </span>
          </Link>
          <nav className="hidden items-center gap-1 lg:flex">
            <Button variant="ghost" className="nav-link" asChild>
              <Link to="/menu">Menu</Link>
            </Button>
            <Button variant="ghost" className="nav-link" asChild>
              <Link to="/orders">Orders</Link>
            </Button>
            <Button variant="ghost" className="nav-link" asChild>
              <Link to="/concierge">
                <Sparkles />
                Ask AI
              </Link>
            </Button>
          </nav>
          <BranchPicker className="hidden sm:flex" />
          <Button
            variant="ghost"
            size="icon"
            className="theme-toggle"
            onClick={store.toggleTheme}
            aria-label={store.dark ? "Use light mode" : "Use dark mode"}
          >
            {/* Keyed so the incoming icon mounts fresh and its entrance runs. */}
            {store.dark ? <Sun key="sun" /> : <Moon key="moon" />}
          </Button>
          <Button variant="ghost" size="icon" asChild aria-label="Account">
            <Link to={isAuthenticated ? "/orders" : "/login"}>
              <UserRound />
            </Link>
          </Button>
          <Button
            size="icon"
            asChild
            aria-label={`Cart with ${store.totalItems} items`}
            className="relative"
          >
            <Link to="/cart">
              <ShoppingBag />
              {/* Keyed on the count so the badge pops each time it changes. */}
              {store.totalItems > 0 && (
                <span className="cart-count" key={store.totalItems}>
                  {store.totalItems}
                </span>
              )}
            </Link>
          </Button>
        </div>
      </header>
      <div className="border-b border-border bg-surface px-4 py-2 sm:hidden">
        <BranchPicker className="w-full" />
      </div>
      <main>{children}</main>
      <nav className="mobile-nav-bar fixed inset-x-0 bottom-0 z-40 grid grid-cols-4 border-t border-border bg-surface px-2 lg:hidden">
        <Link className="mobile-nav" to="/menu">
          <UtensilsCrossed aria-hidden="true" />
          Menu
        </Link>
        <Link className="mobile-nav" to="/concierge">
          <Sparkles aria-hidden="true" />
          Ask AI
        </Link>
        <Link className="mobile-nav" to="/orders">
          <ReceiptText aria-hidden="true" />
          Orders
        </Link>
        <Link className="mobile-nav" to="/cart">
          <ShoppingBag aria-hidden="true" />
          Cart ({store.totalItems})
        </Link>
      </nav>
    </div>
  );
}
