import { Bike, Check, ChevronDown, Clock, MapPin } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { formatMoney } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";

/**
 * Branch switcher.
 *
 * Was a bare `<select>` showing branch names and nothing else. Which branch you
 * order from decides the delivery fee, how long the food takes and whether the
 * kitchen is even open — all of it already on the location record, none of it
 * on screen. A native select also cannot show any of that, renders in the OS's
 * own styling, and was hidden below `sm`, so phone users could not switch
 * branch at all.
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
        <DropdownMenuLabel className="px-2.5 pb-1 pt-2 text-xs font-black uppercase tracking-wide text-muted">
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
                  <span className="flex items-center gap-1">
                    <Bike className="size-3 text-primary" />
                    {Number(location.delivery_fee) === 0
                      ? "Free delivery"
                      : `${formatMoney(location.delivery_fee)} delivery`}
                  </span>
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
