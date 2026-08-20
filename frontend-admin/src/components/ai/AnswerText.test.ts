import { describe, expect, it } from "vitest";

import { parseBlocks } from "./AnswerText";

/**
 * The parser is the half of the renderer that can be wrong quietly: a missed
 * block turns a list back into a paragraph and nobody notices until an owner
 * reads it. The React half is a switch over what this returns.
 */
describe("parseBlocks", () => {
  it("keeps a plain answer as one paragraph", () => {
    // A simple question should stay a simple sentence, with no structure
    // imposed on it.
    expect(parseBlocks("Revenue was ₹1,578.92 in 18 Jun - 16 Aug 2026.")).toEqual([
      { kind: "paragraph", lines: ["Revenue was ₹1,578.92 in 18 Jun - 16 Aug 2026."] },
    ]);
  });

  it("groups consecutive bullets into one list", () => {
    const blocks = parseBlocks("Here is what moved:\n- one\n- two\n- three");
    expect(blocks).toHaveLength(2);
    expect(blocks[1]).toEqual({ kind: "bullets", items: ["one", "two", "three"] });
  });

  it("groups numbered items into one ordered list", () => {
    const blocks = parseBlocks("1. first\n2. second");
    expect(blocks[0]).toEqual({ kind: "numbered", items: ["first", "second"] });
  });

  it("attaches an indented line to the item above it", () => {
    // This is what keeps a recommendation's "why" with its "what" instead of
    // starting a new point.
    const blocks = parseBlocks("1. **Promote Pad Thai**\n   It fell by ₹1,329.");
    expect(blocks[0]).toEqual({
      kind: "numbered",
      items: ["**Promote Pad Thai**\nIt fell by ₹1,329."],
    });
  });

  it("reads a heading", () => {
    expect(parseBlocks("### What changed")).toEqual([
      { kind: "heading", text: "What changed" },
    ]);
  });

  it("separates blocks split by a blank line", () => {
    const blocks = parseBlocks("Lead sentence.\n\n- a\n- b\n\nClosing note.");
    expect(blocks.map((block) => block.kind)).toEqual([
      "paragraph",
      "bullets",
      "paragraph",
    ]);
  });

  it("keeps two paragraphs separated by a blank line apart", () => {
    // The lead sentence and the line introducing a list are different blocks.
    // Merged, the answer read as one run-on paragraph ending in a colon.
    const blocks = parseBlocks("Revenue was up.\n\nHere is what moved most:");
    expect(blocks).toEqual([
      { kind: "paragraph", lines: ["Revenue was up."] },
      { kind: "paragraph", lines: ["Here is what moved most:"] },
    ]);
  });

  it("does not attach an indented line across a blank line", () => {
    const blocks = parseBlocks("1. thing\n\n   stray line");
    expect(blocks).toHaveLength(2);
    expect(blocks[1].kind).toBe("paragraph");
  });

  it("joins wrapped lines of one paragraph", () => {
    const blocks = parseBlocks("first line\nsecond line");
    expect(blocks[0]).toEqual({
      kind: "paragraph",
      lines: ["first line", "second line"],
    });
  });

  it("handles an empty answer", () => {
    // Mid-stream the text is briefly empty; it must not throw.
    expect(parseBlocks("")).toEqual([]);
  });

  it("treats a partial answer as valid", () => {
    // Answers arrive a chunk at a time, so every prefix has to parse.
    const full = "Here is what moved:\n- **Dish** — Pad Thai fell by ₹1,329\n";
    for (let index = 1; index <= full.length; index += 1) {
      expect(() => parseBlocks(full.slice(0, index))).not.toThrow();
    }
  });

  it("leaves unknown markup as text rather than mangling it", () => {
    // Falling through as plain text is the safe direction.
    const blocks = parseBlocks("> quoted\n| a | b |");
    expect(blocks[0].kind).toBe("paragraph");
  });
});
