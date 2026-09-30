import type { OrderLine } from '../lib/api'
import { lineModifiers } from '../lib/board'

/**
 * The dishes on an order, as a kitchen reads them.
 *
 * Shared by the live ticket and the history view so a completed order reads
 * exactly as it did on the rail — same sizes, same groups, same halves. Two
 * renderings of one order would drift, and the one that drifted would be the
 * one a cook trusted while checking what went out.
 *
 * Quantity is the heaviest thing here and always in the same column, because
 * on a busy rail it is the first thing anybody looks for.
 */
export function OrderItems({ items }: { items: OrderLine[] }) {
  return (
    <ul className="kds-items">
      {items.map((line) => {
        const mods = lineModifiers(line)
        return (
          <li className="kds-item" key={line.id}>
            <span className="kds-item__qty">{line.quantity}×</span>
            <div className="kds-item__body">
              <p className="kds-item__name">{line.item_name_snapshot}</p>
              {mods.map((row, index) => (
                <p className="kds-item__mods" key={index}>
                  {row.label ? <span className="kds-item__group">{row.label}</span> : null}
                  {/* A half is a tag, not a word in the sentence: which side
                      gets the pepperoni is the part a cook must not skim. */}
                  {row.half ? (
                    <span className="kds-half" data-half={row.half}>
                      {row.half === 'LEFT' ? 'Left ½' : 'Right ½'}
                    </span>
                  ) : null}
                  <span>{row.text}</span>
                </p>
              ))}
            </div>
          </li>
        )
      })}
    </ul>
  )
}
