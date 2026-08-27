import { describe, expect, it } from "vitest";

import {
  PRIORITY_MAX,
  applyPriorityEdit,
  assignSequentialPriority,
  orderIdsByPriority,
} from "./priority";

describe("orderIdsByPriority", () => {
  it("orders priority asc, nulls last, and keeps input order inside nulls", () => {
    expect(
      orderIdsByPriority(["a", "b", "c", "d"], {
        a: null,
        b: 2,
        c: 1,
        d: null,
      }),
    ).toEqual(["c", "b", "a", "d"]);
  });

  it("treats missing map entries as unprioritized", () => {
    expect(orderIdsByPriority(["a", "b"], { a: 1 })).toEqual(["a", "b"]);
  });
});

describe("assignSequentialPriority (drag semantics)", () => {
  it("assigns 1..N by drop position", () => {
    expect(assignSequentialPriority(["x", "y", "z"])).toEqual({
      x: 1,
      y: 2,
      z: 3,
    });
  });

  it("can never create a duplicate or an out-of-range priority", () => {
    const ids = Array.from({ length: PRIORITY_MAX + 5 }, (_, i) => `c${i}`);
    const result = assignSequentialPriority(ids);
    const values = Object.values(result).filter((v) => v !== null);
    expect(new Set(values).size).toBe(values.length);
    expect(Math.max(...values)).toBeLessThanOrEqual(PRIORITY_MAX);
  });

  it("drops everything past 20 back to unprioritized", () => {
    const ids = Array.from({ length: 22 }, (_, i) => `c${i}`);
    const result = assignSequentialPriority(ids);
    expect(result["c19"]).toBe(20);
    expect(result["c20"]).toBeNull();
    expect(result["c21"]).toBeNull();
  });
});

describe("applyPriorityEdit (manual edits)", () => {
  const ids = ["a", "b", "c"];

  it("sets a free number", () => {
    const { priorities, result } = applyPriorityEdit(
      { a: 1, b: null, c: null },
      "b",
      "2",
      ids,
    );
    expect(result).toEqual({ ok: true, priority: 2 });
    expect(priorities).toEqual({ a: 1, b: 2, c: null });
  });

  it('clears the priority on ""', () => {
    const { priorities, result } = applyPriorityEdit({ a: 1 }, "a", "", ids);
    expect(result).toEqual({ ok: true, priority: null });
    expect(priorities.a).toBeNull();
  });

  it("REJECTS duplicates and leaves the map untouched", () => {
    const before = { a: 1, b: 2, c: null };
    const { priorities, result } = applyPriorityEdit(before, "c", "2", ids);
    expect(result).toEqual({
      ok: false,
      error: "priority_duplicate",
      holderCourseId: "b",
    });
    expect(priorities).toBe(before);
  });

  it("allows keeping the same row's own number", () => {
    const { result } = applyPriorityEdit({ a: 3 }, "a", "3", ids);
    expect(result).toEqual({ ok: true, priority: 3 });
  });

  it.each(["0", "21", "99"])("rejects out-of-range %s", (raw) => {
    const { result } = applyPriorityEdit({ a: null }, "a", raw, ids);
    expect(result).toEqual({
      ok: false,
      error: "priority_range",
      holderCourseId: null,
    });
  });

  it.each(["abc", "1.5", "-1", " 2x"])("rejects non-integer %s", (raw) => {
    const { result } = applyPriorityEdit({ a: null }, "a", raw, ids);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(["priority_invalid", "priority_range"]).toContain(result.error);
    }
  });
});
