/**
 * The realtime status, readable anywhere under `RealtimeProvider`.
 *
 * Kept apart from the provider so each module has one kind of export — React
 * Fast Refresh remounts a file that mixes a component with a hook.
 */

import { createContext, useContext } from "react";

import type { RealtimeStatus } from "@/lib/realtime";

/** `null` while signed out or before hydration: no socket, nothing to say. */
export const RealtimeStatusContext = createContext<RealtimeStatus | null>(null);

export function useRealtimeStatus(): RealtimeStatus | null {
  return useContext(RealtimeStatusContext);
}
