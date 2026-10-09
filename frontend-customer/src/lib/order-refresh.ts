import { queryKeys } from "./queries";

/**
 * What an `order:updated` push (or a reconnect) makes the storefront refetch.
 *
 * The delivery card is in the list on purpose: a rider being assigned,
 * reaching the restaurant or reaching the door does not change the order's
 * status, so the order query alone would show the customer none of it until
 * the delivery card's own 15-second poll came round.
 *
 * `null` means the socket reconnected and anything may have moved.
 */
export function orderQueriesToRefresh(orderIds: string[] | null): readonly (readonly string[])[] {
  if (orderIds === null) {
    return [queryKeys.orders, ["order"], ["payment-status"], ["order-delivery"]];
  }
  return [
    queryKeys.orders,
    ...orderIds.flatMap((id) => [
      queryKeys.order(id),
      ["payment-status", id],
      queryKeys.orderDelivery(id),
    ]),
  ];
}
