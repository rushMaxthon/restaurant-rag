import { useEffect, useId, useMemo, useRef, useState } from "react";

export interface ChartDatum {
  label: string;
  value: number;
  meta?: string;
}

interface AreaPoint extends ChartDatum {
  x: number;
  y: number;
}

interface AreaGeometry {
  points: AreaPoint[];
  yTicks: number[];
  areaPath: string;
  linePath: string;
  plotLeft: number;
  plotTop: number;
  plotWidth: number;
  plotHeight: number;
  maxRounded: number;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function getTickStep(maxValue: number) {
  if (maxValue <= 4) {
    return 1;
  }
  if (maxValue <= 20) {
    return 5;
  }
  if (maxValue <= 60) {
    return 10;
  }
  if (maxValue <= 120) {
    return 20;
  }
  return 50;
}

function buildSmoothLinePath(points: Array<{ x: number; y: number }>) {
  if (points.length === 0) {
    return "";
  }
  if (points.length === 1) {
    return `M ${points[0].x} ${points[0].y}`;
  }

  return points.reduce((path, point, index, array) => {
    if (index === 0) {
      return `M ${point.x} ${point.y}`;
    }
    const previous = array[index - 1];
    const midX = (previous.x + point.x) / 2;
    return `${path} C ${midX} ${previous.y}, ${midX} ${point.y}, ${point.x} ${point.y}`;
  }, "");
}

function buildAreaGeometry(
  data: ChartDatum[],
  width: number,
  height: number,
  padding?: Partial<Pick<AreaGeometry, "plotLeft" | "plotTop" | "plotWidth" | "plotHeight">>,
): AreaGeometry {
  const plotLeft = padding?.plotLeft ?? 48;
  const plotTop = padding?.plotTop ?? 12;
  const plotRight = 18;
  const plotBottom = 32;
  const plotWidth = padding?.plotWidth ?? width - plotLeft - plotRight;
  const plotHeight = padding?.plotHeight ?? height - plotTop - plotBottom;
  const maxValue = Math.max(...data.map((item) => item.value), 1);
  const tickStep = getTickStep(maxValue);
  const maxRounded = Math.ceil(maxValue / tickStep) * tickStep;
  const stepX = data.length === 1 ? 0 : plotWidth / (data.length - 1);
  const yTicks = Array.from({ length: 5 }, (_, index) => Math.round((maxRounded / 4) * index));
  const points = data.map((item, index) => ({
    ...item,
    x: plotLeft + index * stepX,
    y: plotTop + plotHeight - (item.value / maxRounded) * plotHeight,
  }));
  const linePath = buildSmoothLinePath(points);
  return {
    points,
    yTicks,
    areaPath: `${linePath} L ${plotLeft + plotWidth} ${plotTop + plotHeight} L ${plotLeft} ${plotTop + plotHeight} Z`,
    linePath,
    plotLeft,
    plotTop,
    plotWidth,
    plotHeight,
    maxRounded,
  };
}

function useResponsiveWidth() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const node = ref.current;
    if (!node) {
      return;
    }

    const update = () => {
      setWidth(node.clientWidth);
    };

    update();
    const observer = new ResizeObserver(() => update());
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return { ref, width };
}

function getVisibleLabelIndexes(length: number, width: number) {
  if (length <= 1) {
    return new Set([0]);
  }

  // Reserve ~140px per label so long range labels ("02 May - 08 May")
  // never collide, regardless of container width.
  const maxLabels =
    width > 0 ? Math.max(3, Math.min(8, Math.floor(width / 140))) : 5;
  const step = Math.max(1, Math.ceil(length / maxLabels));
  const visible = new Set<number>();
  for (let index = 0; index < length; index += step) {
    visible.add(index);
  }
  // The final point is always labeled; drop a stepped label that would
  // land close enough to collide with it.
  for (const index of visible) {
    if (index !== 0 && index !== length - 1 && length - 1 - index < step * 0.6) {
      visible.delete(index);
    }
  }
  visible.add(length - 1);
  return visible;
}

function formatDefaultValue(value: number) {
  return String(value);
}

export function AreaTrendChart({
  data,
  valueFormatter = formatDefaultValue,
  yTickFormatter = formatDefaultValue,
  seriesLabel,
  className,
  width = 560,
  height = 220,
}: {
  data: ChartDatum[];
  valueFormatter?: (value: number) => string;
  yTickFormatter?: (value: number) => string;
  seriesLabel: string;
  className: string;
  width?: number;
  height?: number;
}) {
  const gradientId = useId();
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const { ref, width: containerWidth } = useResponsiveWidth();
  // Render at the measured pixel width so 1 SVG unit = 1 CSS pixel and
  // axis text is never stretched by non-uniform viewBox scaling.
  const effectiveWidth = containerWidth || width;
  const geometry = useMemo(
    () => buildAreaGeometry(data, effectiveWidth, height),
    [data, effectiveWidth, height],
  );
  const activePoint = hoveredIndex !== null ? geometry.points[hoveredIndex] : null;
  const tooltipAlignLeft = activePoint
    ? activePoint.x > geometry.plotLeft + geometry.plotWidth * 0.72
    : false;
  const visibleLabels = useMemo(
    () => getVisibleLabelIndexes(data.length, containerWidth),
    [containerWidth, data.length],
  );

  return (
    <div className={className} ref={ref}>
      <svg preserveAspectRatio="none" viewBox={`0 0 ${effectiveWidth} ${height}`}>
        <defs>
          <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="rgba(31, 41, 55, 0.18)" />
            <stop offset="52%" stopColor="rgba(148, 163, 184, 0.12)" />
            <stop offset="100%" stopColor="rgba(255, 255, 255, 0.03)" />
          </linearGradient>
        </defs>

        {geometry.yTicks
          .slice()
          .reverse()
          .map((tick, tickIndex) => {
            const y =
              geometry.plotTop +
              geometry.plotHeight -
              (tick / geometry.maxRounded) * geometry.plotHeight;
            return (
              // Indexed: on a series with a small range the rounded ticks can
              // repeat (two 0s, two 1s), and duplicate keys let React drop
              // gridlines.
              <g key={`tick-${tickIndex}`}>
                <line
                  className={`${className}__grid-line`}
                  x1={geometry.plotLeft}
                  x2={geometry.plotLeft + geometry.plotWidth}
                  y1={y}
                  y2={y}
                />
                <text
                  className={`${className}__axis-label`}
                  textAnchor="end"
                  x={geometry.plotLeft - 8}
                  y={y + 4}
                >
                  {yTickFormatter(tick)}
                </text>
              </g>
            );
          })}

        {geometry.points.map((point, index) => (
          <line
            className={`${className}__grid-tick`}
            key={`${point.label}-tick-${index}`}
            x1={point.x}
            x2={point.x}
            y1={geometry.plotTop}
            y2={geometry.plotTop + geometry.plotHeight}
          />
        ))}

        <line
          className={`${className}__axis-line`}
          x1={geometry.plotLeft}
          x2={geometry.plotLeft}
          y1={geometry.plotTop}
          y2={geometry.plotTop + geometry.plotHeight}
        />
        <line
          className={`${className}__axis-line`}
          x1={geometry.plotLeft}
          x2={geometry.plotLeft + geometry.plotWidth}
          y1={geometry.plotTop + geometry.plotHeight}
          y2={geometry.plotTop + geometry.plotHeight}
        />

        <path className={`${className}__area`} d={geometry.areaPath} fill={`url(#${gradientId})`} />
        <path className={`${className}__line`} d={geometry.linePath} />

        {activePoint ? (
          <>
            <line
              className={`${className}__hover-line`}
              x1={activePoint.x}
              x2={activePoint.x}
              y1={activePoint.y}
              y2={geometry.plotTop + geometry.plotHeight}
            />
            <circle
              className={`${className}__dot ${className}__dot--active`}
              cx={activePoint.x}
              cy={activePoint.y}
              r={4}
            />
          </>
        ) : null}

        {geometry.points.map((point, index) => (
          <circle
            className={`${className}__hit`}
            cx={point.x}
            cy={point.y}
            key={`${point.label}-${point.value}`}
            onBlur={() => setHoveredIndex(null)}
            onFocus={() => setHoveredIndex(index)}
            onMouseEnter={() => setHoveredIndex(index)}
            onMouseLeave={() => setHoveredIndex(null)}
            r={16}
            tabIndex={0}
          />
        ))}

        {geometry.points.map((point, index) =>
          visibleLabels.has(index) ? (
            <text
              className={`${className}__axis-label ${className}__axis-label--x`}
              key={`label-${point.label}-${index}`}
              textAnchor="middle"
              x={point.x}
              y={geometry.plotTop + geometry.plotHeight + 18}
            >
              {point.label}
            </text>
          ) : null,
        )}
      </svg>

      {activePoint ? (
        <div
          className={
            tooltipAlignLeft
              ? `${className}__tooltip ${className}__tooltip--left`
              : `${className}__tooltip`
          }
          style={{
            left: `${(activePoint.x / effectiveWidth) * 100}%`,
            top: `${(activePoint.y / height) * 100}%`,
          }}
        >
          <strong>{valueFormatter(activePoint.value)}</strong>
          <div>
            <span>{seriesLabel}</span>
            <span>{valueFormatter(activePoint.value)}</span>
          </div>
          <small>{activePoint.meta ?? activePoint.label}</small>
        </div>
      ) : null}
    </div>
  );
}

export function VerticalBarsChart({
  data,
  className,
  valueFormatter = formatDefaultValue,
}: {
  data: ChartDatum[];
  className: string;
  valueFormatter?: (value: number) => string;
}) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const { ref, width } = useResponsiveWidth();
  const maxValue = Math.max(...data.map((item) => item.value), 1);
  const visibleLabels = useMemo(() => getVisibleLabelIndexes(data.length, width), [data.length, width]);
  const activeItem = hoveredIndex !== null ? data[hoveredIndex] : null;

  return (
    <div className={className} ref={ref}>
      {activeItem ? (
        <div
          className={`${className}__tooltip`}
          style={{
            left: `${clamp((((hoveredIndex ?? 0) + 0.5) / Math.max(data.length, 1)) * 100, 12, 88)}%`,
            top: "6%",
          }}
        >
          <strong>{valueFormatter(activeItem.value)}</strong>
          <div>
            <span>{activeItem.label}</span>
            <span>{valueFormatter(activeItem.value)}</span>
          </div>
          <small>{activeItem.meta ?? activeItem.label}</small>
        </div>
      ) : null}

      {data.map((item, index) => (
        <div
          className={`${className}__item`}
          key={`${item.label}-${index}`}
          onBlur={() => setHoveredIndex(null)}
          onFocus={() => setHoveredIndex(index)}
          onMouseEnter={() => setHoveredIndex(index)}
          onMouseLeave={() => setHoveredIndex(null)}
          tabIndex={0}
        >
          <span className={`${className}__value`}>{valueFormatter(item.value)}</span>
          <div className={`${className}__track`}>
            <div
              className={`${className}__bar`}
              style={{
                height:
                  item.value > 0
                    ? `${Math.max((item.value / maxValue) * 100, 6)}%`
                    : "0%",
              }}
            />
          </div>
          {visibleLabels.has(index) ? <strong>{item.label}</strong> : <strong>&nbsp;</strong>}
          {item.meta ? <small>{item.meta}</small> : null}
        </div>
      ))}
    </div>
  );
}

export function HorizontalBarsChart({
  data,
  className,
  valueFormatter = formatDefaultValue,
}: {
  data: ChartDatum[];
  className: string;
  valueFormatter?: (value: number) => string;
}) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const maxValue = Math.max(...data.map((item) => item.value), 1);
  const activeItem = hoveredIndex !== null ? data[hoveredIndex] : null;

  return (
    <div className={className}>
      {activeItem ? (
        <div
          className={`${className}__tooltip`}
          style={{
            left: `${clamp(((activeItem.value / maxValue) * 100) + 12, 18, 88)}%`,
            top: `${clamp(16 + (hoveredIndex ?? 0) * 20, 10, 86)}%`,
          }}
        >
          <strong>{valueFormatter(activeItem.value)}</strong>
          <div>
            <span>{activeItem.label}</span>
            <span>{valueFormatter(activeItem.value)}</span>
          </div>
          <small>{activeItem.meta ?? activeItem.label}</small>
        </div>
      ) : null}

      {data.map((item, index) => (
        <div
          className={`${className}__row`}
          key={`${item.label}-${index}`}
          onBlur={() => setHoveredIndex(null)}
          onFocus={() => setHoveredIndex(index)}
          onMouseEnter={() => setHoveredIndex(index)}
          onMouseLeave={() => setHoveredIndex(null)}
          tabIndex={0}
        >
          <div className={`${className}__copy`}>
            <strong>{item.label}</strong>
            <span>{item.meta ?? `${valueFormatter(item.value)}`}</span>
          </div>
          <div className={`${className}__track`}>
            <div
              className={`${className}__bar`}
              style={{
                width:
                  item.value > 0
                    ? `${Math.max((item.value / maxValue) * 100, 8)}%`
                    : "0%",
              }}
            />
          </div>
          <strong className={`${className}__value`}>{valueFormatter(item.value)}</strong>
        </div>
      ))}
    </div>
  );
}
