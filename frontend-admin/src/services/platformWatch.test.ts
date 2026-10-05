import { describe, expect, it } from "vitest";

import type { PlatformCheck, PlatformIssue, PlatformWatch } from "../types/app";
import { failingChecks, issuesBySeverity, overallVerdict, verdictHeadline } from "./platformWatch";

const check = (key: string, status: PlatformCheck["status"]): PlatformCheck => ({
  key,
  label: key,
  status,
  detail: "",
  hint: "",
});

const issue = (severity: PlatformIssue["severity"]): PlatformIssue => ({
  key: `k-${severity}`,
  severity,
  title: "t",
  detail: "d",
  count: 1,
  restaurant_id: null,
  restaurant_name: null,
  location_id: null,
  link: null,
});

const watch = (checks: PlatformCheck[], issues: PlatformIssue[] = []): PlatformWatch => ({
  generated_at: "2026-10-05T10:00:00Z",
  checks,
  issues,
  restaurants: [],
});

describe("overallVerdict", () => {
  it("is down when any machinery is down, whatever else is fine", () => {
    expect(overallVerdict(watch([check("db", "ok"), check("beat", "down")]))).toBe("down");
  });

  it("is a warning for a warning check or an urgent restaurant issue", () => {
    expect(overallVerdict(watch([check("ai", "warn")]))).toBe("warn");
    expect(overallVerdict(watch([check("db", "ok")], [issue("high")]))).toBe("warn");
  });

  it("is fine with only minor issues", () => {
    expect(overallVerdict(watch([check("db", "ok")], [issue("low"), issue("medium")]))).toBe("ok");
  });

  it("is fine before anything has loaded, rather than alarming", () => {
    expect(overallVerdict(null)).toBe("ok");
  });
});

describe("verdictHeadline", () => {
  it("counts what is down first", () => {
    expect(verdictHeadline(watch([check("a", "down"), check("b", "down")], [issue("high")]))).toBe(
      "2 parts of the platform are down",
    );
  });

  it("counts urgent issues next, in the singular when there is one", () => {
    expect(verdictHeadline(watch([check("a", "ok")], [issue("high")]))).toBe("1 thing needs attention now");
  });

  it("says plainly when nothing is wrong", () => {
    expect(verdictHeadline(watch([check("a", "ok")]))).toBe("Everything is running");
  });
});

describe("issuesBySeverity and failingChecks", () => {
  it("groups issues by how urgent they are", () => {
    const groups = issuesBySeverity([issue("low"), issue("high"), issue("high")]);
    expect(groups.high).toHaveLength(2);
    expect(groups.medium).toHaveLength(0);
    expect(groups.low).toHaveLength(1);
  });

  it("lists only machinery that is not OK, down before warning", () => {
    const failing = failingChecks([check("a", "warn"), check("b", "ok"), check("c", "down")]);
    expect(failing.map((each) => each.key)).toEqual(["c", "a"]);
  });
});
