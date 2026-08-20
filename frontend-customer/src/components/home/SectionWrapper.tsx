import type { ReactNode } from 'react';

interface SectionWrapperProps {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function SectionWrapper({
  eyebrow,
  title,
  subtitle,
  action,
  children,
  className,
}: SectionWrapperProps) {
  return (
    <section className={className ? `section-card home-section ${className}` : 'section-card home-section'}>
      <div className="section-card__header home-section__header">
        <div className="home-section__copy">
          {eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}
          <h2>{title}</h2>
          {subtitle ? <p className="section-subtle">{subtitle}</p> : null}
        </div>
        {action ? <div className="home-section__action">{action}</div> : null}
      </div>
      {children}
    </section>
  );
}
