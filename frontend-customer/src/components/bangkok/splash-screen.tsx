import { brandInitials } from "@/lib/brand-mark";

/**
 * The restaurant's name, held for a moment on first arrival.
 *
 * A splash screen on a website is usually a mistake: it delays the thing
 * somebody came for, and it makes the largest contentful paint a logo instead
 * of the food. This one earns its place for a narrow reason — the API is a
 * long way from the customer, so a first load already spends about a second
 * filling the menu in behind skeletons. Covering a wait that exists is
 * different from inventing one.
 *
 * Four rules keep it on the right side of that line, and all four are
 * structural rather than a matter of being careful:
 *
 * **It cannot outlast its welcome.** The fade is a CSS animation with
 * `forwards`, not a JavaScript timer waiting on a query. There is no state it
 * can get stuck in: if the bundle never loads, if hydration throws, if the
 * backend is down, the overlay still leaves on time because nothing has to run
 * for it to.
 *
 * **It is once per visit, not once per page.** An inline script in the head
 * sets `data-splash="seen"` from sessionStorage before the first paint, so
 * coming back from the cart does not replay it. Same pre-paint pattern the
 * operator panel uses for its theme, and for the same reason: React cannot run
 * early enough to prevent a flash.
 *
 * **It never hides the page from a crawler.** It is an overlay over
 * server-rendered HTML, `aria-hidden`, and out of the accessibility tree. The
 * menu, the copy and the meta tags are all in the first response whether this
 * renders or not.
 *
 * **Somebody who asked for less motion gets none of it.** Not a shorter
 * animation — none, the overlay is simply never shown.
 */
export function SplashScreen({ name }: { name: string }) {
  return (
    <div className="splash" aria-hidden="true">
      <div className="splash__mark">{brandInitials(name)}</div>
      <p className="splash__name">{name}</p>
    </div>
  );
}

/**
 * Runs before the first paint, so a repeat view never flashes the overlay.
 *
 * Inlined as a string rather than imported: it has to execute in the document
 * head before anything renders, which is earlier than any module this app
 * loads. Wrapped in try/catch because `sessionStorage` throws outright in some
 * privacy modes, and a storefront that fails to render because it could not
 * read a flag would be a far worse bug than showing the splash twice.
 */
export const SPLASH_PREPAINT = `(function(){try{
var k="storefront.splash";
if(sessionStorage.getItem(k)){document.documentElement.setAttribute("data-splash","seen");}
else{sessionStorage.setItem(k,"1");}
}catch(e){}})();`;
