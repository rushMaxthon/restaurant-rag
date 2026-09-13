import { Link } from "@tanstack/react-router";
import { Moon, ShoppingBag, Sparkles, Sun, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BranchPicker } from "./branch-picker";
import { useBangkokStore } from "@/lib/bangkok-store";
import { useAuth } from "@/lib/auth";
export function AppShell({ children }: { children: React.ReactNode }) {
  const store = useBangkokStore();
  const { isAuthenticated } = useAuth();
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-50 border-b border-border bg-surface/95 backdrop-blur">
        <div className="flex min-h-16 w-full items-center gap-3 px-4 sm:px-6 lg:px-10">
          <Link to="/" className="mr-auto flex items-center gap-2" aria-label="Bangkok Bowl home">
            <span className="brand-mark">BB</span>
            <span className="font-display text-xl font-black">
              {store.restaurantName ?? "Bangkok Bowl"}
            </span>
          </Link>
          <nav className="hidden items-center gap-1 lg:flex">
            <Button variant="ghost" asChild>
              <Link to="/menu">Menu</Link>
            </Button>
            <Button variant="ghost" asChild>
              <Link to="/orders">Orders</Link>
            </Button>
            <Button variant="ghost" asChild>
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
            onClick={store.toggleTheme}
            aria-label={store.dark ? "Use light mode" : "Use dark mode"}
          >
            {store.dark ? <Sun /> : <Moon />}
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
              {store.totalItems > 0 && <span className="cart-count">{store.totalItems}</span>}
            </Link>
          </Button>
        </div>
      </header>
      <div className="border-b border-border bg-surface px-4 py-2 sm:hidden">
        <BranchPicker className="w-full" />
      </div>
      <main>{children}</main>
      <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-4 border-t border-border bg-surface px-2 lg:hidden">
        <Link className="mobile-nav" to="/menu">
          Menu
        </Link>
        <Link className="mobile-nav" to="/concierge">
          Ask AI
        </Link>
        <Link className="mobile-nav" to="/orders">
          Orders
        </Link>
        <Link className="mobile-nav" to="/cart">
          Cart ({store.totalItems})
        </Link>
      </nav>
    </div>
  );
}
