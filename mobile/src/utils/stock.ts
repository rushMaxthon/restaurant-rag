/**
 * Whether a dish can be ordered right now.
 *
 * The server is the rule (`backend/app/services/stock.py`) and refuses an
 * order for a dish that is out of stock whatever this app shows. This exists
 * so the app does not offer an Add button the server is going to refuse.
 *
 * Three facts make a dish unavailable: the owner hid it (`is_available`
 * false), the owner marked it out of stock by hand (`out_of_stock`), or it is
 * counted and none are left (`stock_quantity` 0). Null or absent stock means
 * nobody is counting, which is every dish from a server older than the
 * feature - so those two fields are optional and their absence means "yes".
 *
 * Per-size counts are not read here. A dish whose one size has run out still
 * shows an Add button in this app, and the server refuses it at checkout.
 */
type Stocked = {
  is_available?: boolean;
  out_of_stock?: boolean;
  stock_quantity?: number | null;
};

export function isOnSale(item: Stocked | null | undefined): boolean {
  if (!item) {
    return false;
  }
  // `!== false`: a few payloads leave the field out, and absent has always
  // meant available in this app.
  return (
    item.is_available !== false &&
    !item.out_of_stock &&
    item.stock_quantity !== 0
  );
}
