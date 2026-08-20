import { ChevronRight } from 'lucide-react';

export interface BreadcrumbItem {
  label: string;
  path?: string;
}

interface BreadcrumbsProps {
  items: BreadcrumbItem[];
  onNavigate: (path: string) => void;
}

export function Breadcrumbs({ items, onNavigate }: BreadcrumbsProps) {
  return (
    <nav aria-label="Breadcrumb" className="breadcrumbs">
      {items.map((item, index) => {
        const isLast = index === items.length - 1;
        return (
          <span className="breadcrumbs__item" key={`${item.label}-${index}`}>
            {item.path && !isLast ? (
              <button
                className="breadcrumbs__link"
                onClick={() => onNavigate(item.path as string)}
                type="button"
              >
                {item.label}
              </button>
            ) : (
              <span aria-current={isLast ? 'page' : undefined} className="breadcrumbs__current">
                {item.label}
              </span>
            )}
            {!isLast ? (
              <ChevronRight className="breadcrumbs__sep" size={13} strokeWidth={2.2} />
            ) : null}
          </span>
        );
      })}
    </nav>
  );
}
