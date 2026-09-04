import { describe, expect, it } from "vitest";

import type { ScheduleEventDto } from "./api";
import { deriveScheduleState, eventLabel, formatCountdown } from "./schedule";

function ev(
  key: string,
  start: string,
  end: string | null = null,
): ScheduleEventDto {
  return { key, label: key, kind: end !== null ? "window" : "instant", start, end };
}

const EVENTS: ScheduleEventDto[] = [
  ev("first_round_1", "2026-08-20T09:00:00+08:00", "2026-08-21T22:00:00+08:00"),
  ev("first_round_1_result", "2026-08-24T14:00:00+08:00"),
  ev("add_drop_2", "2026-09-09T09:00:00+08:00", "2026-09-11T22:00:00+08:00"),
  ev("withdrawal", "2026-11-13T09:00:00+08:00", "2026-11-20T17:00:00+08:00"),
];

describe("deriveScheduleState", () => {
  it("before everything: all upcoming, next is the earliest start", () => {
    const d = deriveScheduleState(EVENTS, new Date("2026-08-01T12:00:00+08:00"));
    expect(d.active).toBeNull();
    expect(d.next?.event.key).toBe("first_round_1");
    expect(d.next?.kind).toBe("start");
    expect(d.rows.every((row) => row.state === "upcoming")).toBe(true);
  });

  it("inside a window: active is set, next is the nearest future point", () => {
    const d = deriveScheduleState(EVENTS, new Date("2026-08-20T12:00:00+08:00"));
    expect(d.active?.event.key).toBe("first_round_1");
    expect(d.next?.event.key).toBe("first_round_1_result");
    expect(d.next?.kind).toBe("instant");
  });

  it("at a window's end boundary the window is done, not active", () => {
    const d = deriveScheduleState(EVENTS, new Date("2026-08-21T22:00:00+08:00"));
    expect(d.active).toBeNull();
    expect(d.rows[0]!.state).toBe("done");
  });

  it("past instants are done and never become 'next'", () => {
    const d = deriveScheduleState(EVENTS, new Date("2026-09-01T12:00:00+08:00"));
    expect(d.rows[1]!.state).toBe("done");
    expect(d.next?.event.key).toBe("add_drop_2");
  });

  it("after the last event: nothing active, nothing next", () => {
    const d = deriveScheduleState(EVENTS, new Date("2026-12-01T12:00:00+08:00"));
    expect(d.active).toBeNull();
    expect(d.next).toBeNull();
    expect(d.rows.every((row) => row.state === "done")).toBe(true);
  });

  it("malformed rows are skipped instead of breaking the widget", () => {
    const d = deriveScheduleState(
      [ev("broken", "not-a-date"), ...EVENTS],
      new Date("2026-08-01T12:00:00+08:00"),
    );
    expect(d.rows).toHaveLength(EVENTS.length);
  });
});

describe("formatCountdown", () => {
  it("renders days/hours/minutes with the right granularity per lang", () => {
    expect(formatCountdown(3 * 86_400_000 + 5 * 3_600_000, "zh")).toBe("3 天 5 小時");
    expect(formatCountdown(5 * 3_600_000 + 20 * 60_000, "zh")).toBe("5 小時 20 分鐘");
    expect(formatCountdown(40 * 60_000, "zh")).toBe("40 分鐘");
    expect(formatCountdown(30_000, "zh")).toBe("不到 1 分鐘");
    expect(formatCountdown(3 * 86_400_000 + 5 * 3_600_000, "en")).toBe("3d 5h");
    expect(formatCountdown(5 * 3_600_000 + 20 * 60_000, "en")).toBe("5h 20m");
    expect(formatCountdown(30_000, "en")).toBe("<1m");
  });

  it("clamps past targets at zero", () => {
    expect(formatCountdown(-1, "zh")).toBe("不到 1 分鐘");
  });
});

describe("eventLabel", () => {
  it("zh keeps the school's verbatim label; en maps by key with fallback", () => {
    const withdrawal = ev(
      "withdrawal",
      "2026-11-13T09:00:00+08:00",
      "2026-11-20T17:00:00+08:00",
    );
    withdrawal.label = "棄選時間";
    expect(eventLabel(withdrawal, "zh")).toBe("棄選時間");
    expect(eventLabel(withdrawal, "en")).toBe("Course withdrawal");
    const custom = ev("event_3", "2026-10-01T09:00:00+08:00");
    custom.label = "新階段";
    expect(eventLabel(custom, "en")).toBe("新階段");
  });
});
