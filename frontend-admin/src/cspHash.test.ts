import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * The admin's script policy (`vercel.json`, Content-Security-Policy-Report-Only,
 * 2026-10-07 security review) allows exactly one inline script - the
 * dark-mode switch in `index.html` that has to run before the first paint -
 * by its hash. Editing that script without updating the hash would make the
 * policy report it, and block it once the policy is switched to enforcing,
 * so the two are checked against each other here.
 */

const root = fileURLToPath(new URL("..", import.meta.url));

function inlineScripts(html: string): string[] {
  return [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((match) => match[1]);
}

describe("the inline script and the policy that allows it", () => {
  it("every inline script in index.html is allowed by its hash", () => {
    const html = readFileSync(`${root}index.html`, "utf8").replace(/\r\n/g, "\n");
    const config = JSON.parse(readFileSync(`${root}vercel.json`, "utf8")) as {
      headers: Array<{ headers: Array<{ key: string; value: string }> }>;
    };
    const policy =
      config.headers[0].headers.find((header) => header.key === "Content-Security-Policy-Report-Only")
        ?.value ?? "";
    const scripts = inlineScripts(html);
    expect(scripts.length).toBeGreaterThan(0);
    for (const body of scripts) {
      const hash = createHash("sha256").update(body, "utf8").digest("base64");
      expect(policy, "update the sha256 in vercel.json").toContain(`'sha256-${hash}'`);
    }
  });
});
