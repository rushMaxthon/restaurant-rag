import { DatabaseZap, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { StatePanel } from './StatePanel';

interface EmptyPanelProps {
  title: string;
  description: string;
  action?: ReactNode;
  /** Overrides the default database glyph where a subject-specific one reads better. */
  icon?: LucideIcon;
}

export function EmptyPanel({ title, description, action, icon = DatabaseZap }: EmptyPanelProps) {
  return <StatePanel action={action} description={description} icon={icon} title={title} />;
}
