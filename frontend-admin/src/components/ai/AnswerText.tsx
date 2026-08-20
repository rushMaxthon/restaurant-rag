import { Fragment, type ReactNode } from "react";

/**
 * Renders the small Markdown subset the answer formatter emits.
 *
 * Deliberately not a Markdown library. The backend produces exactly four
 * constructs — headings, bullet lists, numbered lists, and bold — and a parser
 * that handles only those is a few lines, has no dependency, and cannot be
 * surprised by input it was not designed for. Anything it does not recognise
 * falls through as plain text, which is the safe direction: an unformatted
 * answer is readable, a mangled one is not.
 *
 * Nothing here is `dangerouslySetInnerHTML`. Every node is built from parsed
 * text, so an answer containing HTML renders as the characters it is.
 */

const BOLD_PATTERN = /\*\*([^*]+)\*\*/g;

/** Splits `a **b** c` into text and <strong> nodes. */
function inline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  BOLD_PATTERN.lastIndex = 0;
  while ((match = BOLD_PATTERN.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    nodes.push(<strong key={`${keyPrefix}-b${match.index}`}>{match[1]}</strong>);
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes.length > 0 ? nodes : [text];
}

type Block =
  | { kind: "heading"; text: string }
  | { kind: "paragraph"; lines: string[] }
  | { kind: "bullets"; items: string[] }
  | { kind: "numbered"; items: string[] };

const BULLET = /^[-*]\s+/;
const NUMBERED = /^\d+\.\s+/;

/**
 * Groups lines into blocks.
 *
 * Consecutive list lines become one list, so a five-item list is one `<ul>`
 * rather than five. A continuation line indented under a numbered item belongs
 * to that item — that is how a recommendation carries its reason on a second
 * line without becoming a separate point.
 */
export function parseBlocks(answer: string): Block[] {
  const blocks: Block[] = [];
  const lines = (answer ?? "").split("\n");
  // A blank line ends whatever block was open. Without this, two paragraphs
  // separated by a blank line merged into one, because the second line still
  // found a paragraph at the end of the list and appended itself to it.
  let blockBroken = false;

  for (const raw of lines) {
    const line = raw.trimEnd();
    const trimmed = line.trim();
    const previous = blockBroken ? undefined : blocks[blocks.length - 1];

    if (!trimmed) {
      blockBroken = true;
      continue;
    }
    blockBroken = false;

    if (trimmed.startsWith("### ")) {
      blocks.push({ kind: "heading", text: trimmed.slice(4) });
      continue;
    }

    if (BULLET.test(trimmed)) {
      const item = trimmed.replace(BULLET, "");
      if (previous?.kind === "bullets") {
        previous.items.push(item);
      } else {
        blocks.push({ kind: "bullets", items: [item] });
      }
      continue;
    }

    if (NUMBERED.test(trimmed)) {
      const item = trimmed.replace(NUMBERED, "");
      if (previous?.kind === "numbered") {
        previous.items.push(item);
      } else {
        blocks.push({ kind: "numbered", items: [item] });
      }
      continue;
    }

    // An indented line continues the list item above it rather than starting a
    // paragraph, which is what keeps "why" attached to its "what".
    if (raw.startsWith("  ") && (previous?.kind === "numbered" || previous?.kind === "bullets")) {
      previous.items[previous.items.length - 1] += `\n${trimmed}`;
      continue;
    }

    if (previous?.kind === "paragraph") {
      previous.lines.push(trimmed);
    } else {
      blocks.push({ kind: "paragraph", lines: [trimmed] });
    }
  }

  return blocks;
}

/** One list item, which may carry a second line of explanation. */
function Item({ text, index }: { text: string; index: number }) {
  const [first, ...rest] = text.split("\n");
  return (
    <li>
      <span className="ai-answer__item-lead">{inline(first, `i${index}`)}</span>
      {rest.map((line, offset) => (
        <span className="ai-answer__item-note" key={`${index}-${offset}`}>
          {inline(line, `i${index}-${offset}`)}
        </span>
      ))}
    </li>
  );
}

export function AnswerText({ text }: { text: string }) {
  const blocks = parseBlocks(text);

  if (blocks.length === 0) {
    return null;
  }

  return (
    <div className="ai-answer">
      {blocks.map((block, index) => {
        switch (block.kind) {
          case "heading":
            return (
              <h4 className="ai-answer__heading" key={index}>
                {inline(block.text, `h${index}`)}
              </h4>
            );
          case "bullets":
            return (
              <ul className="ai-answer__list" key={index}>
                {block.items.map((item, offset) => (
                  <Item text={item} index={offset} key={offset} />
                ))}
              </ul>
            );
          case "numbered":
            return (
              <ol className="ai-answer__list ai-answer__list--numbered" key={index}>
                {block.items.map((item, offset) => (
                  <Item text={item} index={offset} key={offset} />
                ))}
              </ol>
            );
          default:
            return (
              <p key={index}>
                {block.lines.map((line, offset) => (
                  <Fragment key={offset}>
                    {offset > 0 ? " " : null}
                    {inline(line, `p${index}-${offset}`)}
                  </Fragment>
                ))}
              </p>
            );
        }
      })}
    </div>
  );
}
