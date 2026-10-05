// "Orders changed" — the one signal every order screen listens to.
//
// An advance from this tablet, a socket push, or the app waking from sleep
// all mean the same thing: what is on screen may be stale. The board, the
// completed list and an open order each refetch over REST when told. Nothing
// travels on this bus but the fact of a change; REST stays the only source of
// what an order looks like.
type Listener = () => void;

const listeners = new Set<Listener>();

export const ordersChanged = (): void => {
  listeners.forEach(listener => listener());
};

export const onOrdersChanged = (listener: Listener): (() => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};
