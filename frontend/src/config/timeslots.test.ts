import { describe, expect, it } from "vitest";

import {
  PERIOD_CODES,
  TIMESLOTS,
  WEEKDAYS,
  UnknownPeriodCodeError,
  assertPeriodCode,
  formatTimeTag,
  isPeriodCode,
  parseDayTimeString,
} from "./timeslots";

describe("TIMESLOTS config integrity", () => {
  it("contains exactly the 15 period codes in chronological order", () => {
    expect(PERIOD_CODES).toEqual([
      "A", "1", "2", "3", "4", "B", "5", "6",
      "7", "8", "9", "C", "D", "E", "F",
    ]);
    expect(TIMESLOTS).toHaveLength(15);
  });

  it("every code is a single character", () => {
    for (const code of PERIOD_CODES) {
      expect(code).toHaveLength(1);
    }
  });

  it("covers the exact NSYSU clock ranges", () => {
    const ranges = TIMESLOTS.map((t) => `${t.code}=${t.start}–${t.end}`);
    expect(ranges).toEqual([
      "A=07:00–07:50",
      "1=08:10–09:00",
      "2=09:10–10:00",
      "3=10:10–11:00",
      "4=11:10–12:00",
      "B=12:10–13:00",
      "5=13:10–14:00",
      "6=14:10–15:00",
      "7=15:10–16:00",
      "8=16:10–17:00",
      "9=17:10–18:00",
      "C=18:20–19:10",
      "D=19:15–20:05",
      "E=20:10–21:00",
      "F=21:05–21:55",
    ]);
  });

  it("periods are strictly ascending and non-empty", () => {
    for (let i = 0; i < TIMESLOTS.length; i++) {
      const slot = TIMESLOTS[i];
      expect(slot).toBeDefined();
      if (slot === undefined) continue;
      expect(slot.endMin).toBeGreaterThan(slot.startMin);
      if (i > 0) {
        const prev = TIMESLOTS[i - 1];
        expect(prev).toBeDefined();
        if (prev !== undefined) {
          expect(slot.startMin).toBeGreaterThanOrEqual(prev.endMin);
        }
      }
    }
  });

  it("WEEKDAYS covers Monday..Sunday with API values 1..7", () => {
    expect(WEEKDAYS.map((d) => d.label)).toEqual([
      "一", "二", "三", "四", "五", "六", "日",
    ]);
    expect(WEEKDAYS.map((d) => d.apiWeekday)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(WEEKDAYS.map((d) => d.index)).toEqual([0, 1, 2, 3, 4, 5, 6]);
  });
});

describe("parseDayTimeString", () => {
  it("parses a valid day string into period codes", () => {
    expect([...parseDayTimeString("56")].sort()).toEqual(["5", "6"]);
    expect(parseDayTimeString("").size).toBe(0);
  });

  it("accepts every one of the 15 codes", () => {
    const all = parseDayTimeString(PERIOD_CODES.join(""));
    expect(all.size).toBe(15);
  });

  it("throws on unknown codes (never silently passes)", () => {
    expect(() => parseDayTimeString("Z")).toThrow(UnknownPeriodCodeError);
    expect(() => parseDayTimeString("1Z")).toThrow(UnknownPeriodCodeError);
    expect(() => parseDayTimeString("0")).toThrow(UnknownPeriodCodeError);
    expect(() => assertPeriodCode("X")).toThrow(UnknownPeriodCodeError);
    expect(isPeriodCode("Z")).toBe(false);
    expect(isPeriodCode("5")).toBe(true);
  });
});

describe("formatTimeTag", () => {
  it("renders 三56 for Wednesday periods 5,6", () => {
    expect(formatTimeTag(2, "56")).toBe("三56");
    expect(formatTimeTag(0, "A")).toBe("一A");
  });

  it("throws on unknown codes in tags too", () => {
    expect(() => formatTimeTag(2, "5Z")).toThrow(UnknownPeriodCodeError);
  });
});
