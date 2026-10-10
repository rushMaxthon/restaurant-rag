import React from 'react';
import Svg, { Defs, LinearGradient, Path, Rect, Stop } from 'react-native-svg';

import { MARK_LINES, MARK_R, MARK_VIEWBOX } from './brandMarkPaths';

/**
 * Rydorgo's mark - the launcher icon, drawn (no image to load): the italic R
 * and its speed lines in white on the brand gradient. `bare` drops the tile
 * for a surface that is already the brand orange (the splash).
 */
export function BrandMark({
  size = 72,
  bare = false,
}: {
  size?: number;
  bare?: boolean;
}) {
  return (
    <Svg width={size} height={size} viewBox={MARK_VIEWBOX}>
      {bare ? null : (
        <>
          <Defs>
            <LinearGradient
              id="mark"
              x1="18"
              y1="18"
              x2="90"
              y2="90"
              gradientUnits="userSpaceOnUse"
            >
              <Stop offset="0" stopColor="#FF7A3D" />
              <Stop offset="0.55" stopColor="#FF5200" />
              <Stop offset="1" stopColor="#E84A00" />
            </LinearGradient>
          </Defs>
          <Rect
            x={18}
            y={18}
            width={72}
            height={72}
            rx={72 * 0.28}
            fill="url(#mark)"
          />
        </>
      )}
      <Path d={MARK_LINES} fill="#FFFFFF" fillOpacity={0.85} />
      <Path d={MARK_R} fill="#FFFFFF" fillRule="evenodd" />
    </Svg>
  );
}
