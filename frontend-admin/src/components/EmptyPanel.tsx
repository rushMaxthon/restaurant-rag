import { DatabaseZap } from "lucide-react";
import type { ReactNode } from "react";

interface EmptyPanelProps {
  title: string;
  description: string;
  action?: ReactNode;
}

export function EmptyPanel({ title, description, action }: EmptyPanelProps) {
  return (
    <div className="empty-panel">
      <span className="empty-panel__icon">
        <DatabaseZap size={18} strokeWidth={2.1} />
      </span>
      <strong>{title}</strong>
      <span>{description}</span>
      {action ? <div className="empty-panel__action">{action}</div> : null}
    </div>
  );
}
