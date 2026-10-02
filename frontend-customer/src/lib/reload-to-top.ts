/**
 * The key TanStack Router stores its scroll positions under.
 *
 * Read from its source rather than guessed, and the one piece of coupling in
 * this file. If the library renames it, the script below finds nothing, does
 * nothing, and a reload goes back to restoring its old position — which is
 * where this started, so the failure is a return to the previous behaviour
 * rather than a broken page.
 */
const TSR_SCROLL_KEY = "tsr-scroll-restoration-v1_3";

/**
 * A reload starts at the top of the page.
 *
 * The router takes `history.scrollRestoration` off the browser and owns it
 * itself, caching a position per history entry in `sessionStorage`. A reload
 * re-enters the SAME history entry, so the cache has a position for it and the
 * page comes back exactly where it was left — correct for back and forward,
 * and not what anybody means by refreshing a page.
 *
 * So the entry for THIS history key is dropped before the router can read it.
 * Dropping only this one matters: clearing the whole cache would also forget
 * where every other page in the session was, and back would start landing at
 * the top of pages it should restore.
 *
 * **It has to run before the router does**, which means in the document head,
 * before any module this app loads — the same constraint, and the same
 * solution, as `SPLASH_PREPAINT`.
 *
 * Everything is inside try/catch because `sessionStorage` throws outright in
 * some privacy modes, and a storefront that fails to render because it could
 * not forget a scroll position would be a far worse bug than the one this
 * fixes.
 */
export const RELOAD_TO_TOP_PREPAINT = `(function(){try{
var n=performance.getEntriesByType("navigation")[0];
if(!n||n.type!=="reload"){return;}
var k=(history.state&&history.state.__TSR_key)||location.href;
var raw=sessionStorage.getItem(${JSON.stringify(TSR_SCROLL_KEY)});
if(!raw){return;}
var cache=JSON.parse(raw);
if(cache&&cache[k]){delete cache[k];sessionStorage.setItem(${JSON.stringify(TSR_SCROLL_KEY)},JSON.stringify(cache));}
}catch(e){}})();`;
