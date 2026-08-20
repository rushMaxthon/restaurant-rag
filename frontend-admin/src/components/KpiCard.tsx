import type { ReactNode } from 'react';

interface KpiCardProps {
  label: string;
  value: string;
  trend?: string;
  icon?: ReactNode;
  tone?: 'default' | 'accent' | 'success' | 'warning';
}

export function KpiCard({ label, value, trend, icon, tone = 'default' }: KpiCardProps) {
  return (
    <article className={`kpi-card kpi-card--${tone}`}>
      <div className="kpi-card__top">
        <span>{label}</span>
        {icon ? <div className="kpi-card__icon">{icon}</div> : null}
      </div>
      <strong>{value}</strong>
      {trend ? <p>{trend}</p> : null}
    </article>
  );
}
