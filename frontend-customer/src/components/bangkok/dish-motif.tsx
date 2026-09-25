import { useId } from "react";

import type { Motif } from "@/lib/dish-motif";

/**
 * The drawing that stands in for a dish with no photograph.
 *
 * Inline SVG rather than files: there are 136 dishes on a menu page and 82 of
 * them have no picture, so anything fetched would be 82 requests to say "no
 * picture". These cost nothing, stay crisp at any size, and — because every
 * stroke is `currentColor` — take the restaurant's own brand colour without
 * this file knowing what it is.
 *
 * Drawn on one 64×48 grid so every motif sits at the same optical weight in
 * the same tile. Strokes, mostly, and generous space around them: at a glance
 * down a menu these have to read as a texture, not as clip art competing with
 * the dish names beside them.
 */

const STROKE = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

/** Steamed and cut into squares: dhokla, khaman, idada. */
function Squares() {
  return (
    <g {...STROKE}>
      {[0, 1, 2].map((row) =>
        [0, 1, 2].map((col) => (
          <rect
            key={`${row}-${col}`}
            x={20 + col * 9}
            y={12 + row * 9}
            width={7}
            height={7}
            rx={1.6}
            opacity={row === 1 && col === 1 ? 1 : 0.55}
          />
        )),
      )}
    </g>
  );
}

/** A mound of grains: biryani, pulao, every rice. */
function Grains() {
  return (
    <g {...STROKE}>
      <path d="M18 34c0-7 6-13 14-13s14 6 14 13" />
      <path d="M14 34h36" />
      {[
        [26, 27],
        [32, 24],
        [38, 27],
        [29, 31],
        [35, 31],
      ].map(([x, y], i) => (
        <ellipse
          key={i}
          cx={x}
          cy={y}
          rx={2.1}
          ry={1.2}
          opacity={0.6}
          transform={`rotate(${i * 27} ${x} ${y})`}
        />
      ))}
    </g>
  );
}

/** Round, flat and blistered: roti, paratha, chapati. */
function Flatbread() {
  return (
    <g {...STROKE}>
      <circle cx={32} cy={24} r={14} />
      <circle cx={32} cy={24} r={9.5} opacity={0.45} />
      {[
        [27, 20],
        [36, 22],
        [30, 29],
        [37, 28],
      ].map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={1.3} opacity={0.7} />
      ))}
    </g>
  );
}

/** Strands: noodles, hakka, chowmein. */
function Noodles() {
  return (
    <g {...STROKE}>
      {[16, 23, 30].map((y, i) => (
        <path key={y} d={`M14 ${y}c6-5 12 5 18 0s12-5 18 0`} opacity={i === 1 ? 1 : 0.55} />
      ))}
      <path d="M17 36h30" opacity={0.4} />
    </g>
  );
}

/** A bowl with something hot in it: soup, dal, curry, gravy. */
function Bowl() {
  return (
    <g {...STROKE}>
      <path d="M14 26h36c0 8-8 13-18 13s-18-5-18-13Z" />
      <path d="M26 17c0-3 3-3 3-6" opacity={0.6} />
      <path d="M33 15c0-3 3-3 3-6" opacity={0.75} />
      <path d="M40 17c0-3 3-3 3-6" opacity={0.6} />
    </g>
  );
}

/** Cut into cubes: paneer, kofta, kaju, tikka, most starters. */
function Cubes() {
  return (
    <g {...STROKE}>
      {[
        [20, 26],
        [29, 19],
        [38, 26],
      ].map(([x, y], i) => (
        <rect key={i} x={x} y={y} width={9} height={9} rx={2} opacity={i === 1 ? 1 : 0.6} />
      ))}
      <path d="M15 38h34" opacity={0.4} />
    </g>
  );
}

/** A plate ringed with katoris. */
function Thali() {
  return (
    <g {...STROKE}>
      <circle cx={32} cy={24} r={15} />
      {[0, 1, 2, 3, 4].map((i) => {
        const angle = (i / 5) * Math.PI * 2 - Math.PI / 2;
        return (
          <circle
            key={i}
            cx={32 + Math.cos(angle) * 9.5}
            cy={24 + Math.sin(angle) * 9.5}
            r={3.4}
            opacity={0.65}
          />
        );
      })}
    </g>
  );
}

/** Green things. */
function Leaf() {
  return (
    <g {...STROKE}>
      <path d="M32 39c0-11 5-19 15-21 1 12-5 21-15 21Z" />
      <path d="M32 39c0-9-4-15-12-17-1 10 4 17 12 17Z" opacity={0.55} />
      <path d="M32 39V24" opacity={0.7} />
    </g>
  );
}

/** True of everything that ever reached a table. */
function Plate() {
  return (
    <g {...STROKE}>
      <circle cx={32} cy={24} r={14.5} />
      <circle cx={32} cy={24} r={8} opacity={0.4} />
    </g>
  );
}

const MOTIFS: Record<Motif, () => React.ReactElement> = {
  squares: Squares,
  grains: Grains,
  flatbread: Flatbread,
  noodles: Noodles,
  bowl: Bowl,
  cubes: Cubes,
  thali: Thali,
  leaf: Leaf,
  plate: Plate,
};

/**
 * The single glyph the repeat is printed from.
 *
 * The repeat used to tile the whole drawing shrunk down, which fragmented:
 * each cell showed a clipped piece of a bowl or half a stack of cubes, and
 * the result read as scribble rather than pattern. A print is made from ONE
 * simple unit — a grain, a square, a leaf — so that is what these are, drawn
 * on a 12×12 cell with room around them.
 */
const MARKS: Record<Motif, () => React.ReactElement> = {
  squares: () => <rect x={3} y={3} width={6} height={6} rx={1.4} />,
  grains: () => <ellipse cx={6} cy={6} rx={3.4} ry={1.7} transform="rotate(-24 6 6)" />,
  flatbread: () => <circle cx={6} cy={6} r={3.6} />,
  noodles: () => <path d="M2 6c1.6-2.2 3.2 2.2 4.8 0S9.4 3.8 10.8 6" />,
  bowl: () => <path d="M2.4 5h7.2c0 2.6-1.6 4.2-3.6 4.2S2.4 7.6 2.4 5Z" />,
  cubes: () => (
    <rect x={3.2} y={3.2} width={5.6} height={5.6} rx={1.6} transform="rotate(14 6 6)" />
  ),
  thali: () => (
    <>
      <circle cx={6} cy={6} r={3.8} />
      <circle cx={6} cy={6} r={1.2} opacity={0.6} />
    </>
  ),
  leaf: () => <path d="M6 10c0-4 1.8-6.6 5-7.2C11.4 7 8.8 10 6 10Z" />,
  plate: () => <circle cx={6} cy={6} r={3.8} />,
};

/**
 * The drawing twice: printed small across the whole tile, and once at size in
 * the middle.
 *
 * One mark centred in a 440px card reads as a stray icon in an empty box —
 * which is the look this was meant to replace. Printed as a repeat it becomes
 * a surface, the way a paper liner or a wrapping paper does, and the tile has
 * something in every part of it instead of a hole around a glyph.
 *
 * The repeat is set at an angle and offset per dish so two tiles of the same
 * category standing next to each other on the grid do not line up into an
 * obvious tessellation.
 */
export function DishMotif({ motif, seed = 0 }: { motif: Motif; seed?: number }) {
  const Drawing = MOTIFS[motif];
  const Mark = MARKS[motif];
  // `useId` rather than the motif name: two tiles of the same category on one
  // page would otherwise declare the same pattern id, and the second one wins
  // for both.
  const patternId = `motif-${useId().replace(/:/g, "")}`;
  const angle = -18 + (seed % 5) * 9;

  return (
    <svg
      aria-hidden="true"
      className="dish-motif__art"
      viewBox="0 0 64 48"
      preserveAspectRatio="xMidYMid slice"
    >
      <defs>
        {/* A 12-unit cell holding one 12-unit glyph, so nothing is clipped at
            the cell edge. Rotated and nudged per dish so two tiles of the same
            category side by side do not line up into a visible grid. */}
        <pattern
          id={patternId}
          width="12"
          height="12"
          patternUnits="userSpaceOnUse"
          patternTransform={`rotate(${angle}) translate(${(seed % 3) * 4} ${(seed % 2) * 5})`}
        >
          <g {...STROKE} strokeWidth={0.9}>
            <Mark />
          </g>
        </pattern>
      </defs>
      <rect className="dish-motif__print" width="64" height="48" fill={`url(#${patternId})`} />
      <g className="dish-motif__focal">
        <Drawing />
      </g>
    </svg>
  );
}
