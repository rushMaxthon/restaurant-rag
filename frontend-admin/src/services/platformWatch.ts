/**
 * The sums and words behind the Platform watch page, apart from the page so
 * they can be checked without rendering one.
 */
import type { PlatformCheck, PlatformIssue, PlatformWatch } from "../types/app";

export type Verdict = "ok" | "warn" | "down";

/**
 * One word for the whole platform, from the worst thing found.
 *
 * A machine that is down outranks everything; a high-severity issue in a
 * restaurant is as bad as a warning about the machinery, because both mean a
 * customer is affected right now.
 */
export function overallVerdict(watch: PlatformWatch | null): Verdict {
  if (!watch) return "ok";
  if (watch.checks.some((check) => check.status === "down")) return "down";
  if (
    watch.checks.some((check) => check.status === "warn") ||
    watch.issues.some((issue) => issue.severity === "high")
  ) {
    return "warn";
  }
  return "ok";
}

export function verdictHeadline(watch: PlatformWatch | null): string {
  if (!watch) return "Checking the platform…";
  const down = watch.checks.filter((check) => check.status === "down").length;
  const high = watch.issues.filter((issue) => issue.severity === "high").length;
  if (down > 0) return `${down} part${down === 1 ? "" : "s"} of the platform ${down === 1 ? "is" : "are"} down`;
  if (high > 0) return `${high} thing${high === 1 ? "" : "s"} need${high === 1 ? "s" : ""} attention now`;
  if (watch.issues.length > 0) return "Running. A few things are worth a look";
  return "Everything is running";
}

export function issuesBySeverity(issues: PlatformIssue[]): Record<PlatformIssue["severity"], PlatformIssue[]> {
  const groups: Record<PlatformIssue["severity"], PlatformIssue[]> = { high: [], medium: [], low: [] };
  for (const issue of issues) groups[issue.severity].push(issue);
  return groups;
}

/** Machinery that is not OK, worst first, for the strip at the top. */
export function failingChecks(checks: PlatformCheck[]): PlatformCheck[] {
  const rank: Record<Verdict, number> = { down: 0, warn: 1, ok: 2 };
  return checks.filter((check) => check.status !== "ok").sort((a, b) => rank[a.status] - rank[b.status]);
}

export const SEVERITY_LABEL: Record<PlatformIssue["severity"], string> = {
  high: "Needs action now",
  medium: "Should be looked at today",
  low: "Worth knowing",
};
