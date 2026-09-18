import { Check, ChevronDown, Clock, MapPin } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import { useBangkokStore } from "@/lib/bangkok-store";

/**
 * Branch switcher.
 *
 * Was a bare `<select>` showing branch names and nothing else. Which branch you
 * order from decides how long the food takes and whether the kitchen is even
 * open — both already on the location record, neither on screen. A native
 * select also cannot show any of that, renders in the OS's own styling, and
 * was hidden below `sm`, so phone users could not switch branch at all.
 *
 * The delivery fee used to sit here too and was deliberately removed. It is
 * the one number on this list a customer cannot act on yet: the fee that ends
 * up on their bill depends on where they are having it delivered, which they
 * have not told us at the point of choosing a branch. Quoting it here invites
 * them to compare branches on a figure that may not survive checkout — and
 * where a chain charges the same at every branch, it was six identical lines
 * of noise. Checkout is where the fee belongs, against a real address.
 */
export function BranchPicker({ className }: { className?: string }) {
  const store = useBangkokStore();
  if (store.locations.length === 0) return null;

  const current = store.currentLocation;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={`branch-trigger ${className ?? ""}`}
        aria-label="Choose branch"
      >
        <MapPin className="size-4 shrink-0 text-primary" />
        <span className="min-w-0 flex-1 truncate text-left">
          {current?.branch_name ?? "Choose branch"}
        </span>
        {current && !current.is_open && <span className="branch-closed-dot" aria-hidden="true" />}
        <ChevronDown className="size-4 shrink-0 text-muted" />
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-[min(92vw,22rem)] p-1.5">
        <DropdownMenuLabel className="px-2.5 pb-1 pt-2 text-xs font-extrabold uppercase tracking-wide text-muted">
          {store.restaurantName ?? "Branches"}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {store.locations.map((location) => {
          const selected = location.id === store.branchId;
          return (
            <DropdownMenuItem
              key={location.id}
              onSelect={() => store.setBranchId(location.id)}
              className="branch-option"
              data-selected={selected}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate font-bold">{location.branch_name}</span>
                  {location.is_open ? (
                    <span className="branch-pill branch-pill--open">Open</span>
                  ) : (
                    <span className="branch-pill branch-pill--shut">Closed</span>
                  )}
                </div>
                <p className="mt-0.5 truncate text-xs text-muted">
                  {location.address_line_1}, {location.city}
                </p>
                <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-semibold">
                  {location.estimated_delivery_time != null &&
                    location.estimated_delivery_time !== "" && (
                      <span className="flex items-center gap-1">
                        <Clock className="size-3 text-primary" />
                        {location.estimated_delivery_time}
                        {typeof location.estimated_delivery_time === "number" ? " min" : ""}
                      </span>
                    )}
                </p>
              </div>
              {selected && <Check className="size-4 shrink-0 text-primary" />}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
