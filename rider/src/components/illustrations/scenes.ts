/**
 * The app's illustrations, as SVG templates on one 240 x 160 canvas.
 *
 * Templates, not image files: `{P}`-style tokens are filled from the theme
 * (`palette.ts`), so every picture follows light, dark and high contrast and
 * costs a few kilobytes of text instead of a PNG per density. Drawn flat, in
 * the brand orange plus neutrals, from a few shared parts (the scooter, the
 * blob behind each scene, the ground shadow) so they read as one set.
 *
 * Tokens: P brand, PD brand deep, PS brand soft (the blob), G ground, L line
 * (tyres, outlines), B body (paper, screens), BE body edge, SC scooter body,
 * SK skin, HR hair, JN trousers, S success, SS success soft, W warm yellow,
 * K kraft (paper bags), WH white.
 */

const BLOB =
  '<path d="M28 92 C22 52 66 18 120 18 C176 18 216 50 212 92 C208 130 168 146 118 144 C64 142 33 128 28 92 Z" fill="{PS}"/>';

const shadow = (cx: number, cy: number, rx: number) =>
  `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${rx * 0.09}" fill="{G}"/>`;

/** A delivery scooter facing right, 120 wide; wheels touch y = 76 (local). */
function scooter(x: number, y: number, s: number, rider: boolean): string {
  const riderParts = rider
    ? `<path d="M44 40 L66 44 L71 57" stroke="{JN}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
       <rect x="65" y="55" width="13" height="5" rx="2.5" fill="{L}"/>
       <path d="M41 41 C38 29 43 16 53 14 C61 13 67 18 69 26 L62 41 Z" fill="{P}"/>
       <path d="M59 21 L79 27 L90 22" stroke="{P}" stroke-width="6.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
       <circle cx="91" cy="22" r="3.2" fill="{SK}"/>
       <circle cx="57" cy="6" r="8" fill="{SK}"/>
       <path d="M48 7 C48 -6 66 -8 67 4 L67 8 L48 8 Z" fill="{PD}"/>
       <path d="M59 0 L69 2 L68 9 L60 8 Z" fill="{L}" fill-opacity="0.85"/>`
    : '';
  return `<g transform="translate(${x} ${y}) scale(${s})">
    ${shadow(62, 77, 54)}
    <circle cx="28" cy="64" r="12" fill="{L}"/><circle cx="28" cy="64" r="4.5" fill="{B}"/>
    <circle cx="96" cy="64" r="12" fill="{L}"/><circle cx="96" cy="64" r="4.5" fill="{B}"/>
    <rect x="2" y="14" width="34" height="28" rx="5" fill="{P}"/>
    <rect x="2" y="14" width="34" height="9" rx="4.5" fill="{PD}"/>
    <rect x="12" y="29" width="14" height="5" rx="2.5" fill="{WH}" fill-opacity="0.9"/>
    <path d="M14 60 C12 48 22 42 36 42 L70 42 C77 42 81 47 83 53 L86 62 L40 62 C30 62 20 64 14 60 Z" fill="{SC}"/>
    <rect x="40" y="57" width="46" height="6" rx="3" fill="{BE}"/>
    <path d="M28 40 C28 35 33 34 40 34 L62 34 C66 34 66 40 61 40 Z" fill="{L}"/>
    ${riderParts}
    <path d="M80 60 L90 24 L97 26 L88 62 Z" fill="{SC}"/>
    <rect x="84" y="19" width="18" height="5" rx="2.5" fill="{L}"/>
    <circle cx="99" cy="34" r="4" fill="{W}"/>
    <path d="M84 58 C88 50 103 49 108 58 L104 60 C100 54 92 54 88 60 Z" fill="{P}"/>
  </g>`;
}

const speedLines = (x: number, y: number) =>
  `<g fill="{P}" fill-opacity="0.45">
    <rect x="${x + 8}" y="${y}" width="22" height="4.5" rx="2.25"/>
    <rect x="${x}" y="${y + 11}" width="30" height="4.5" rx="2.25"/>
    <rect x="${x + 10}" y="${y + 22}" width="20" height="4.5" rx="2.25"/>
  </g>`;

const pin = (x: number, y: number, s = 1) =>
  `<g transform="translate(${x} ${y}) scale(${s})">
    <path d="M0 -26 C-11 -26 -18 -18 -18 -9 C-18 4 0 18 0 18 C0 18 18 4 18 -9 C18 -18 11 -26 0 -26 Z" fill="{P}"/>
    <circle cx="0" cy="-9" r="6.5" fill="{WH}"/>
  </g>`;

const bag = (x: number, y: number, s = 1) =>
  `<g transform="translate(${x} ${y}) scale(${s})">
    <path d="M6 -30 C6 -42 22 -42 22 -30" stroke="{L}" stroke-width="2.5" fill="none" stroke-linecap="round"/>
    <path d="M0 -30 L28 -30 L30 0 L-2 0 Z" fill="{K}"/>
    <rect x="-2" y="-30" width="32" height="6" fill="{L}" fill-opacity="0.12"/>
    <rect x="8" y="-17" width="12" height="5" rx="2.5" fill="{P}"/>
  </g>`;

const sparkle = (x: number, y: number, r: number, fill: string) =>
  `<path d="M${x} ${y - r} L${x + r * 0.28} ${y - r * 0.28} L${x + r} ${y} L${
    x + r * 0.28
  } ${y + r * 0.28} L${x} ${y + r} L${x - r * 0.28} ${y + r * 0.28} L${
    x - r
  } ${y} L${x - r * 0.28} ${y - r * 0.28} Z" fill="${fill}"/>`;

const svg = (body: string) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 160">${body}</svg>`;

export const SCENES = {
  /** The splash: a rider on the move, no background (it sits on the orange). */
  ride: svg(`${speedLines(28, 72)}
    ${scooter(64, 46, 0.86, true)}`),

  /** Sign in and the splash: on the road, a city behind. */
  road: svg(`${BLOB}
    <g fill="{BE}">
      <rect x="40" y="50" width="22" height="60" rx="3"/><rect x="64" y="36" width="18" height="74" rx="3"/>
      <rect x="84" y="60" width="20" height="50" rx="3"/><rect x="150" y="44" width="20" height="66" rx="3"/>
      <rect x="172" y="58" width="26" height="52" rx="3"/>
    </g>
    <g fill="{B}" fill-opacity="0.75">
      <rect x="46" y="58" width="4" height="5"/><rect x="53" y="58" width="4" height="5"/><rect x="46" y="70" width="4" height="5"/>
      <rect x="69" y="46" width="4" height="5"/><rect x="69" y="58" width="4" height="5"/><rect x="155" y="52" width="4" height="5"/>
      <rect x="162" y="52" width="4" height="5"/><rect x="155" y="64" width="4" height="5"/><rect x="178" y="66" width="4" height="5"/>
      <rect x="186" y="66" width="4" height="5"/>
    </g>
    <circle cx="196" cy="36" r="10" fill="{W}"/>
    <rect x="14" y="108" width="212" height="22" rx="11" fill="{G}"/>
    <path d="M30 119 L210 119" stroke="{B}" stroke-width="2.5" stroke-dasharray="10 8" stroke-linecap="round"/>
    ${speedLines(34, 72)}
    ${scooter(70, 46, 0.86, true)}
    ${pin(212, 96, 0.6)}`),

  /** Intro 1, going online: sunrise over a parked scooter. */
  goOnline: svg(`${BLOB}
    <circle cx="120" cy="96" r="44" fill="{W}" fill-opacity="0.9"/>
    <g stroke="{W}" stroke-width="4" stroke-linecap="round">
      <path d="M120 34 L120 24"/><path d="M76 52 L69 45"/><path d="M164 52 L171 45"/><path d="M60 92 L50 92"/><path d="M180 92 L190 92"/>
    </g>
    <path d="M24 114 C60 96 96 104 120 104 C150 104 184 94 216 112 C214 128 186 142 120 142 C58 142 28 130 24 114 Z" fill="{G}"/>
    ${scooter(68, 58, 0.82, false)}`),

  /** Intro 2, an order arrives: a phone ringing, the order card on it. */
  newOrder: svg(`${BLOB}
    <g stroke="{P}" stroke-width="4" stroke-linecap="round" fill="none" stroke-opacity="0.55">
      <path d="M74 48 C64 60 64 84 74 96"/><path d="M62 38 C46 58 46 86 62 106"/>
      <path d="M166 48 C176 60 176 84 166 96"/><path d="M178 38 C194 58 194 86 178 106"/>
    </g>
    ${shadow(120, 146, 40)}
    <rect x="86" y="18" width="68" height="126" rx="12" fill="{L}"/>
    <rect x="91" y="26" width="58" height="110" rx="8" fill="{B}"/>
    <rect x="97" y="40" width="46" height="46" rx="23" fill="{PS}"/>
    <path d="M120 50 C111 50 107 57 107 64 L107 72 L103 76 L137 76 L133 72 L133 64 C133 57 129 50 120 50 Z" fill="{P}"/>
    <circle cx="120" cy="79" r="4" fill="{P}"/>
    <rect x="97" y="96" width="46" height="8" rx="4" fill="{BE}"/>
    <rect x="97" y="110" width="30" height="8" rx="4" fill="{BE}"/>
    <rect x="97" y="122" width="46" height="10" rx="5" fill="{S}"/>
    ${sparkle(58, 120, 7, '{W}')}${sparkle(186, 26, 6, '{P}')}`),

  /** Intro 3, pick up: the restaurant, the bag on the counter. */
  pickup: svg(`${BLOB}
    ${shadow(120, 140, 80)}
    <rect x="52" y="52" width="136" height="86" rx="4" fill="{B}"/>
    <rect x="52" y="52" width="136" height="86" rx="4" fill="none" stroke="{BE}" stroke-width="2"/>
    <path d="M44 34 L196 34 L196 52 L44 52 Z" fill="{P}"/>
    <g fill="{WH}"><rect x="63" y="34" width="13" height="18"/><rect x="89" y="34" width="13" height="18"/><rect x="115" y="34" width="13" height="18"/><rect x="141" y="34" width="13" height="18"/><rect x="167" y="34" width="13" height="18"/></g>
    <path d="M44 52 C50 60 57 60 63 52 C69 60 76 60 82 52 C88 60 95 60 101 52 C107 60 114 60 120 52 C126 60 133 60 139 52 C145 60 152 60 158 52 C164 60 171 60 177 52 C183 60 190 60 196 52 Z" fill="{PD}"/>
    <rect x="62" y="72" width="54" height="40" rx="3" fill="{PS}"/>
    <rect x="134" y="72" width="38" height="66" rx="3" fill="{BE}"/>
    <circle cx="164" cy="106" r="2.5" fill="{L}"/>
    <rect x="58" y="112" width="62" height="8" rx="2" fill="{L}"/>
    ${bag(76, 112, 0.95)}
    ${sparkle(206, 74, 7, '{W}')}`),

  /** Intro 4, hand over: the customer's door, the code, done. */
  handover: svg(`${BLOB}
    ${shadow(104, 142, 66)}
    <rect x="58" y="30" width="80" height="110" rx="4" fill="{BE}"/>
    <rect x="66" y="38" width="64" height="102" rx="3" fill="{PD}"/>
    <rect x="74" y="48" width="48" height="36" rx="3" fill="{P}"/>
    <rect x="74" y="92" width="48" height="40" rx="3" fill="{P}"/>
    <circle cx="118" cy="90" r="3.5" fill="{W}"/>
    <rect x="48" y="136" width="100" height="8" rx="3" fill="{G}"/>
    ${bag(150, 136, 0.95)}
    <rect x="150" y="30" width="72" height="34" rx="10" fill="{B}"/>
    <path d="M164 62 L160 74 L174 63 Z" fill="{B}"/>
    <g fill="{P}"><circle cx="166" cy="47" r="4"/><circle cx="180" cy="47" r="4"/><circle cx="194" cy="47" r="4"/></g>
    <circle cx="210" cy="47" r="7" fill="{S}"/>
    <path d="M206.5 47 L209 49.5 L213.5 44.5" stroke="{WH}" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`),

  /** Orders board empty: the map is quiet, the rider waits nearby. */
  waiting: svg(`${BLOB}
    ${shadow(104, 144, 46)}
    <rect x="66" y="16" width="76" height="128" rx="13" fill="{L}"/>
    <rect x="71" y="24" width="66" height="112" rx="9" fill="{B}"/>
    <g stroke="{BE}" stroke-width="5" stroke-linecap="round">
      <path d="M71 56 L137 48"/><path d="M71 100 L137 108"/><path d="M96 24 L92 136"/><path d="M120 24 L124 136"/>
    </g>
    <circle cx="104" cy="80" r="30" fill="{P}" fill-opacity="0.12"/>
    <circle cx="104" cy="80" r="18" fill="{P}" fill-opacity="0.18"/>
    ${pin(104, 82, 0.7)}
    ${scooter(146, 96, 0.5, false)}
    <g fill="{M}" fill-opacity="0.7"><circle cx="196" cy="60" r="3"/><circle cx="206" cy="48" r="4"/><circle cx="218" cy="34" r="5"/></g>`),

  /** Home, off shift: the scooter parked under the moon. */
  resting: svg(`${BLOB}
    <path d="M178 22 C162 24 152 38 154 54 C156 70 172 80 188 76 C178 70 172 58 174 46 C176 34 182 26 190 22 C186 21 182 21 178 22 Z" fill="{W}"/>
    ${sparkle(54, 40, 6, '{W}')}${sparkle(80, 22, 4, '{W}')}${sparkle(
    140,
    30,
    5,
    '{W}',
  )}
    <rect x="22" y="128" width="196" height="10" rx="5" fill="{G}"/>
    ${scooter(58, 62, 0.86, false)}
    <path d="M84 91 C84 80 100 78 104 86 L105 92 L84 92 Z" fill="{PD}"/>`),

  /** History empty: a road waiting for its first trip, the flag at its end. */
  noTrips: svg(`${BLOB}
    <path d="M40 146 C70 120 40 96 90 86 C140 76 110 52 170 44" stroke="{G}" stroke-width="22" stroke-linecap="round" fill="none"/>
    <path d="M40 146 C70 120 40 96 90 86 C140 76 110 52 170 44" stroke="{B}" stroke-width="2.5" stroke-dasharray="8 8" stroke-linecap="round" fill="none"/>
    <path d="M176 46 L176 8" stroke="{L}" stroke-width="3" stroke-linecap="round"/>
    <path d="M177 9 L204 16 L177 26 Z" fill="{P}"/>
    ${shadow(176, 47, 14)}
    <circle cx="58" cy="128" r="7" fill="{P}"/><circle cx="58" cy="128" r="3" fill="{WH}"/>
    ${sparkle(206, 62, 6, '{W}')}${sparkle(34, 70, 5, '{P}')}`),

  /** A screen that could not load: no signal. */
  offline: svg(`${BLOB}
    ${shadow(120, 138, 56)}
    <path d="M78 116 C62 116 54 104 56 92 C58 80 70 74 80 76 C84 58 100 48 118 50 C136 52 148 64 150 78 C164 76 178 86 178 100 C178 110 170 116 160 116 Z" fill="{B}" stroke="{BE}" stroke-width="3"/>
    <g stroke="{M}" stroke-width="5" stroke-linecap="round" fill="none">
      <path d="M100 92 C110 84 128 84 138 92"/><path d="M108 101 C114 97 124 97 130 101"/>
    </g>
    <circle cx="119" cy="108" r="3.5" fill="{M}"/>
    <path d="M92 70 L148 120" stroke="{P}" stroke-width="5" stroke-linecap="round"/>`),

  /** Delivered: the bag at the door, the scooter already leaving. */
  delivered: svg(`${BLOB}
    <rect x="20" y="132" width="200" height="8" rx="4" fill="{G}"/>
    <rect x="36" y="44" width="56" height="88" rx="3" fill="{BE}"/>
    <rect x="42" y="50" width="44" height="82" rx="2" fill="{PD}"/>
    <circle cx="80" cy="94" r="3" fill="{W}"/>
    ${bag(56, 132, 0.8)}
    ${speedLines(108, 82)}
    ${scooter(132, 74, 0.68, true)}
    ${sparkle(110, 40, 7, '{W}')}${sparkle(196, 34, 5, '{P}')}`),

  /** Application, not sent yet: the papers to fill in. */
  apply: svg(`${BLOB}
    ${shadow(116, 146, 50)}
    <rect x="72" y="26" width="88" height="116" rx="8" fill="{B}" stroke="{BE}" stroke-width="2.5"/>
    <rect x="98" y="18" width="36" height="16" rx="5" fill="{L}"/>
    <rect x="84" y="46" width="26" height="30" rx="4" fill="{PS}"/>
    <circle cx="97" cy="56" r="6" fill="{SK}"/>
    <path d="M87 74 C87 66 107 66 107 74 Z" fill="{P}"/>
    <g fill="{BE}"><rect x="116" y="50" width="32" height="6" rx="3"/><rect x="116" y="64" width="22" height="6" rx="3"/>
      <rect x="84" y="88" width="64" height="6" rx="3"/><rect x="84" y="102" width="52" height="6" rx="3"/><rect x="84" y="116" width="58" height="6" rx="3"/></g>
    <path d="M168 66 L178 56 L186 64 L176 74 L164 78 Z" fill="{P}"/>
    <path d="M178 56 L184 50 L192 58 L186 64 Z" fill="{L}"/>
    ${sparkle(54, 52, 6, '{W}')}`),

  /** Application sent: the team is reading it. */
  review: svg(`${BLOB}
    ${shadow(112, 146, 52)}
    <rect x="84" y="30" width="72" height="96" rx="7" fill="{BE}" transform="rotate(8 120 78)"/>
    <rect x="70" y="34" width="76" height="104" rx="7" fill="{B}" stroke="{BE}" stroke-width="2.5"/>
    <g fill="{BE}"><rect x="82" y="50" width="52" height="6" rx="3"/><rect x="82" y="64" width="40" height="6" rx="3"/><rect x="82" y="78" width="48" height="6" rx="3"/><rect x="82" y="92" width="30" height="6" rx="3"/></g>
    <circle cx="142" cy="96" r="22" fill="{B}" fill-opacity="0.6" stroke="{P}" stroke-width="7"/>
    <path d="M158 112 L178 132" stroke="{P}" stroke-width="10" stroke-linecap="round"/>
    <g transform="translate(50 64)">
      <path d="M0 0 L22 0 M0 40 L22 40" stroke="{L}" stroke-width="4" stroke-linecap="round"/>
      <path d="M3 2 C3 14 19 14 19 20 C19 26 3 26 3 38 L19 38 C19 26 3 26 3 20 C3 14 19 14 19 2 Z" fill="{B}" stroke="{L}" stroke-width="2.5"/>
      <path d="M6 33 L16 33 L11 26 Z" fill="{W}"/>
    </g>`),

  /** Application sent back: one thing to fix. */
  fixes: svg(`${BLOB}
    ${shadow(116, 146, 50)}
    <rect x="72" y="26" width="88" height="116" rx="8" fill="{B}" stroke="{BE}" stroke-width="2.5"/>
    <g fill="{BE}"><rect x="86" y="44" width="58" height="6" rx="3"/><rect x="86" y="58" width="44" height="6" rx="3"/>
      <rect x="86" y="100" width="54" height="6" rx="3"/><rect x="86" y="114" width="38" height="6" rx="3"/></g>
    <rect x="80" y="74" width="72" height="16" rx="5" fill="{W}" fill-opacity="0.35"/>
    <rect x="86" y="79" width="48" height="6" rx="3" fill="{W}"/>
    <path d="M150 104 L184 70 L194 80 L160 114 L146 118 Z" fill="{P}"/>
    <path d="M184 70 L190 64 L200 74 L194 80 Z" fill="{L}"/>
    <circle cx="62" cy="46" r="14" fill="{W}"/>
    <rect x="60" y="37" width="4" height="11" rx="2" fill="{WH}"/><circle cx="62" cy="53" r="2.4" fill="{WH}"/>`),

  /** Approved: the rider's card, ticked. */
  approved: svg(`${BLOB}
    ${shadow(116, 140, 60)}
    <rect x="58" y="42" width="116" height="84" rx="10" fill="{B}" stroke="{BE}" stroke-width="2.5"/>
    <rect x="58" y="42" width="116" height="20" rx="10" fill="{P}"/>
    <rect x="58" y="54" width="116" height="8" fill="{P}"/>
    <rect x="70" y="72" width="34" height="40" rx="5" fill="{PS}"/>
    <circle cx="87" cy="85" r="8" fill="{SK}"/>
    <path d="M74 110 C74 98 100 98 100 110 Z" fill="{P}"/>
    <g fill="{BE}"><rect x="112" y="76" width="48" height="6" rx="3"/><rect x="112" y="90" width="34" height="6" rx="3"/><rect x="112" y="104" width="42" height="6" rx="3"/></g>
    <circle cx="174" cy="44" r="20" fill="{S}"/>
    <path d="M165 44 L171 50 L184 37" stroke="{WH}" stroke-width="5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
    ${sparkle(46, 40, 7, '{W}')}${sparkle(206, 96, 6, '{P}')}${sparkle(
    40,
    120,
    5,
    '{S}',
  )}
    <rect x="196" y="22" width="6" height="12" rx="2" fill="{W}" transform="rotate(30 199 28)"/>
    <rect x="30" y="76" width="6" height="12" rx="2" fill="{P}" transform="rotate(-25 33 82)"/>`),
} as const;

export type SceneName = keyof typeof SCENES;
