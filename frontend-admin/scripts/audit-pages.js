/**
 * What the panel actually looks like, measured rather than eyeballed.
 *
 * Reads the RENDERED document — computed colours, real geometry — and reports
 * four things no build step and no unit test can see:
 *
 *   leaks     a surface, border or gradient painted on the wrong side of the
 *             current theme: a white card on a dark page, or the reverse.
 *   contrast  every run of text, against the background it ACTUALLY sits on
 *             (walking up for the first opaque ancestor), with the WCAG AA
 *             threshold for its size and weight.
 *   tiny      interactive elements under 28px tall.
 *   overflow  a box whose content is wider than it is.
 *
 * It exists because every defect fixed on 2026-10-01 was invisible: the panel
 * looked fine in a screenshot and failed when the numbers were taken. Seventy-
 * six distinct contrast failures, eight to thirteen on every page, none of
 * them reported by anything.
 *
 * ## Running it
 *
 * With the dev server up, paste this whole file into the browser console on
 * any admin page. It returns an object; `JSON.stringify(result, null, 1)` is
 * the readable form. To walk several pages, stash it first so it survives the
 * navigations:
 *
 *     localStorage.__audit = <this file as a string>
 *     // then on each page:
 *     eval(localStorage.__audit)
 *
 * Check both themes. Half of what it found only appeared in one of them.
 *
 * ## What it deliberately does NOT answer
 *
 * `gradientText` lists elements whose backdrop is a gradient. It refuses to
 * guess at those rather than reporting the page behind them — which it used
 * to do, and which produced a confident 1.04:1 for white text on a perfectly
 * legible orange button. A wrong number is worse than no number: it sends you
 * to fix something that is not broken. Measure those by hand.
 *
 * It also has no opinion about layout, hierarchy or whether a screen makes
 * sense. It only knows whether what is on it can be read.
 */

(() => {
  const dark = document.documentElement.classList.contains('dark');
  // `color-mix()` computes to `color(srgb r g b / a)` with 0-1 components, not
  // 0-255 — read as rgb that made every frosted panel look near-black.
  const rgb = (c) => { const s = String(c); const m = s.match(/[\d.]+/g); if (!m) return null;
    const unit = /^color\(/.test(s) ? 255 : 1;
    const a = m[3] !== undefined ? +m[3] : 1;
    return { r:+m[0]*unit, g:+m[1]*unit, b:+m[2]*unit, a }; };
  const lin = (v) => { v /= 255; return v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); };
  const lum = (c) => c ? 0.2126*lin(c.r) + 0.7152*lin(c.g) + 0.0722*lin(c.b) : null;
  const over = (fg, bg) => ({ r: fg.r*fg.a + bg.r*(1-fg.a), g: fg.g*fg.a + bg.g*(1-fg.a), b: fg.b*fg.a + bg.b*(1-fg.a), a: 1 });
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); const hi = Math.max(l1,l2), lo = Math.min(l1,l2); return (hi+0.05)/(lo+0.05); };
  // Stops at a gradient and says so. Walking PAST one reports the page behind
  // the button as the backdrop, which produced a confident 1.04:1 for white
  // text on a perfectly legible orange button — a wrong number is worse than
  // no number, because it sends you to fix something that is not broken.
  const effBg = (el) => { let n = el;
    while (n && n !== document.documentElement) { const cs = getComputedStyle(n);
      const c = rgb(cs.backgroundColor);
      if (c && c.a >= 0.95) return c;
      if (/gradient/.test(cs.backgroundImage)) return null;
      n = n.parentElement; }
    return rgb(getComputedStyle(document.body).backgroundColor) || { r:255,g:255,b:255,a:1 }; };
  const name = (el) => (el.tagName.toLowerCase() + '.' + (typeof el.className === 'string' ? el.className.trim().split(/\s+/).slice(0,2).join('.') : '')).slice(0, 52);
  const seen = new Set();
  const push = (list, key, obj) => { const k = key; if (seen.has(k)) return; seen.add(k); list.push(obj); };

  const root = document.querySelector('.admin-layout__main') || document.body;
  const leaks = [], contrast = [], tiny = [], overflow = [], numeric = [], gradientText = [];

  for (const el of root.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;

    // 1. theme leaks: a surface whose lightness is on the wrong side of the theme
    const bg = rgb(cs.backgroundColor);
    if (bg && bg.a >= 0.4 && r.width > 36 && r.height > 12) {
      const L = lum(bg);
      if (dark && L > 0.5) push(leaks, 'bg|' + name(el), { kind:'light-bg-in-dark', el:name(el), v:cs.backgroundColor });
      if (!dark && L < 0.12 && !el.closest('.admin-sidebar')) push(leaks, 'bg|' + name(el), { kind:'dark-bg-in-light', el:name(el), v:cs.backgroundColor });
    }
    const bi = cs.backgroundImage;
    if (/gradient/.test(bi) && r.width > 80 && r.height > 30) {
      const stops = (bi.match(/rgba?\([^)]+\)|#[0-9a-f]{3,8}/gi) || []).map(rgb).filter(c => c && c.a >= 0.5);
      if (stops.length) { const L = stops.map(lum);
        if (dark && Math.max(...L) > 0.5) push(leaks, 'grad|' + name(el), { kind:'light-gradient-in-dark', el:name(el), v:bi.slice(0,60) });
        if (!dark && Math.min(...L) < 0.1 && !el.closest('.admin-sidebar')) push(leaks, 'grad|' + name(el), { kind:'dark-gradient-in-light', el:name(el), v:bi.slice(0,60) }); }
    }
    // Per side. Reading borderTopColor when only border-bottom is set returns
    // the element's `color`, which made every dark-mode heading with an
    // underline look like a white hairline.
    for (const side of ['Top','Right','Bottom','Left']) {
      if (!(parseFloat(cs['border' + side + 'Width']) > 0)) continue;
      if (cs['border' + side + 'Style'] === 'none') continue;
      const bc = rgb(cs['border' + side + 'Color']);
      if (bc && bc.a >= 0.5 && dark && lum(bc) > 0.55)
        push(leaks, 'bd|' + name(el) + side, { kind:'light-border-in-dark', el:name(el) + ':' + side.toLowerCase(), v:cs['border' + side + 'Color'] });
    }

    // 2. contrast of leaf text
    const txt = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 1);
    if (txt) {
      const fg = rgb(cs.color);
      if (fg && fg.a > 0.1) {
        const bgc = effBg(el);
        if (bgc === null) { gradientText.push(name(el)); continue; }
        const c = ratio(fg.a < 1 ? over(fg, bgc) : fg, bgc);
        const size = parseFloat(cs.fontSize), weight = +cs.fontWeight || 400;
        const large = size >= 24 || (size >= 18.66 && weight >= 700);
        const need = large ? 3 : 4.5;
        if (c < need) push(contrast, 'c|' + name(el) + '|' + cs.color, { el:name(el), text:el.textContent.trim().slice(0,32), color:cs.color, on:`rgb(${Math.round(bgc.r)},${Math.round(bgc.g)},${Math.round(bgc.b)})`, ratio:+c.toFixed(2), need, size });
      }
    }

    // 3. undersized interactive targets
    if (/^(button|a|select|input)$/.test(el.tagName.toLowerCase()) && cs.pointerEvents !== 'none') {
      if (r.height > 0 && r.height < 28 && r.width > 0 && !el.closest('.admin-sidebar'))
        push(tiny, 't|' + name(el), { el:name(el), w:Math.round(r.width), h:Math.round(r.height), text:(el.textContent||el.getAttribute('aria-label')||'').trim().slice(0,24) });
    }

    // 4. horizontal overflow
    if (el.scrollWidth > el.clientWidth + 2 && cs.overflowX !== 'auto' && cs.overflowX !== 'scroll' && el.clientWidth > 0)
      push(overflow, 'o|' + name(el), { el:name(el), scroll:el.scrollWidth, client:el.clientWidth });
  }

  // 5. numbers that are not right-aligned / not tabular
  for (const td of root.querySelectorAll('table td')) {
    const t = td.textContent.trim();
    if (!/^[^A-Za-z]*[\p{Sc}]?\s?[\d,]+(\.\d+)?\s?%?[^A-Za-z]*$/u.test(t) || t.length === 0) continue;
    const cs = getComputedStyle(td);
    if (cs.textAlign !== 'right' || !/tabular-nums/.test(cs.fontVariantNumeric))
      push(numeric, 'n|' + td.cellIndex + '|' + location.pathname, { col:td.cellIndex, sample:t.slice(0,16), align:cs.textAlign, nums:cs.fontVariantNumeric });
  }

  const docOverflow = document.documentElement.scrollWidth > window.innerWidth + 2;
  const h1 = document.querySelector('.admin-layout__main h1');
  return { path: location.pathname, theme: dark ? 'dark' : 'light',
    h1: h1 ? { text: h1.textContent.trim().slice(0,30), size: getComputedStyle(h1).fontSize, weight: getComputedStyle(h1).fontWeight } : null,
    docOverflow, leaks, gradientText: [...new Set(gradientText)], contrast: contrast.slice(0,14), tiny: tiny.slice(0,10), overflow: overflow.slice(0,6), numeric };
})()
