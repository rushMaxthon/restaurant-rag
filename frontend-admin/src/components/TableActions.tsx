import type { LucideIcon } from "lucide-react";
import { MoreHorizontal } from "lucide-react";

export type TableActionTone = "default" | "danger" | "success";

export interface TableAction<Row> {
  id: string;
  label: string;
  icon: LucideIcon;
  onClick: (row: Row) => void;
  tone?: TableActionTone;
  hidden?: (row: Row) => boolean;
  disabled?: (row: Row) => boolean;
}

interface TableActionsProps<Row> {
  row: Row;
  actions: Array<TableAction<Row>>;
  compact?: boolean;
}

function getToneClass(tone: TableActionTone | undefined): string {
  switch (tone) {
    case "danger":
      return "table-icon-button table-icon-button--danger";
    case "success":
      return "table-icon-button table-icon-button--success";
    default:
      return "table-icon-button";
  }
}

export function TableActions<Row>({
  row,
  actions,
  compact = false,
}: TableActionsProps<Row>) {
  const visibleActions = actions.filter((action) =>
    action.hidden ? !action.hidden(row) : true,
  );

  if (visibleActions.length === 0) {
    return <span className="hint-text">No actions</span>;
  }

  const primaryActions = visibleActions.slice(0, compact ? 2 : 3);
  const overflowActions = visibleActions.slice(compact ? 2 : 3);

  return (
    <div
      className={compact ? "table-actions table-actions--compact" : "table-actions"}
      onClick={(event) => event.stopPropagation()}
    >
      {primaryActions.map((action) => {
        const Icon = action.icon;
        const disabled = action.disabled ? action.disabled(row) : false;

        return (
          <button
            aria-label={action.label}
            className={getToneClass(action.tone)}
            disabled={disabled}
            key={action.id}
            onClick={() => action.onClick(row)}
            title={action.label}
            type="button"
          >
            <Icon size={16} strokeWidth={2.1} />
          </button>
        );
      })}

      {overflowActions.length > 0 ? (
        <details
          className="table-action-menu"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.currentTarget.removeAttribute("open");
            }
          }}
        >
          <summary
            aria-label="More actions"
            className="table-icon-button"
            onClick={(event) => event.stopPropagation()}
          >
            <MoreHorizontal size={16} strokeWidth={2.1} />
          </summary>
          <div className="table-action-menu__dropdown">
            {overflowActions.map((action) => {
              const Icon = action.icon;
              const disabled = action.disabled ? action.disabled(row) : false;

              return (
                <button
                  className={
                    action.tone === "danger"
                      ? "table-action-menu__item table-action-menu__item--danger"
                      : "table-action-menu__item"
                  }
                  disabled={disabled}
                  key={action.id}
                  onClick={() => action.onClick(row)}
                  type="button"
                >
                  <Icon size={15} strokeWidth={2.1} />
                  <span>{action.label}</span>
                </button>
              );
            })}
          </div>
        </details>
      ) : null}
    </div>
  );
}
