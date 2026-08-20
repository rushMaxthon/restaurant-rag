import {
  AreaTrendChart,
  VerticalBarsChart,
  type ChartDatum,
} from "./AnimatedCharts";

interface MiniChartDatum {
  label: string;
  value: number;
}

interface MiniChartProps {
  title: string;
  subtitle: string;
  data: MiniChartDatum[];
  mode?: 'bar' | 'line';
  valueFormatter?: (value: number) => string;
}

export function MiniChart({
  title,
  subtitle,
  data,
  mode = 'bar',
  valueFormatter,
}: MiniChartProps) {
  const chartData: ChartDatum[] = data;

  return (
    <article className="chart-card">
      <div className="chart-card__header">
        <div>
          <h3>{title}</h3>
          <p>{subtitle}</p>
        </div>
      </div>
      {mode === "line" ? (
        <AreaTrendChart
          className="mini-chart"
          data={chartData}
          height={180}
          seriesLabel={title}
          valueFormatter={valueFormatter}
          width={320}
        />
      ) : (
        <VerticalBarsChart className="mini-chart" data={chartData} valueFormatter={valueFormatter} />
      )}
    </article>
  );
}
