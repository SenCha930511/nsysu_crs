import { describe, expect, it } from "vitest";

import type { PlanOut } from "./api";
import { hasPrimaryInvariant, plansReducer } from "./plansState";
import type { PlansListState } from "./plansState";

function plan(id: string, name: string, isPrimary = false): PlanOut {
  return {
    id,
    name,
    is_primary: isPrimary,
    item_count: 0,
    created_at: "2026-08-28T00:00:00+08:00",
    updated_at: null,
  };
}

function state(plans: PlanOut[], activePlanId: string | null = null): PlansListState {
  return { plans, activePlanId };
}

describe("plansReducer primary invariants", () => {
  it("first created plan is the (only) primary and becomes active", () => {
    const next = plansReducer(state([]), { type: "created", plan: plan("a", "A", true) });
    expect(next.activePlanId).toBe("a");
    expect(hasPrimaryInvariant(next)).toBe(true);
  });

  it("primarySet leaves EXACTLY ONE primary", () => {
    const before = state([plan("a", "A", true), plan("b", "B")], "a");
    const next = plansReducer(before, { type: "primarySet", planId: "b" });
    expect(next.plans.map((p) => p.is_primary)).toEqual([false, true]);
    expect(hasPrimaryInvariant(next)).toBe(true);
  });

  it("deleting the primary promotes the remaining plan", () => {
    const before = state([plan("a", "A", true), plan("b", "B")], "a");
    const next = plansReducer(before, {
      type: "removed",
      planId: "a",
      promotedPlanId: "b",
    });
    expect(next.plans).toHaveLength(1);
    expect(next.plans[0]?.is_primary).toBe(true);
    expect(next.activePlanId).toBe("b");
    expect(hasPrimaryInvariant(next)).toBe(true);
  });

  it("deleting a non-primary plan never disturbs the current primary", () => {
    const before = state([plan("a", "A", true), plan("b", "B")], "b");
    const next = plansReducer(before, {
      type: "removed",
      planId: "b",
      promotedPlanId: null,
    });
    expect(next.plans).toHaveLength(1);
    expect(next.plans[0]?.is_primary).toBe(true);
    expect(next.activePlanId).toBe("a");
  });
});

describe("plansReducer active-plan switching", () => {
  it("activeSelected moves only the active id (priorities stay per-plan)", () => {
    const before = state([plan("a", "A", true), plan("b", "B")], "a");
    const next = plansReducer(before, { type: "activeSelected", planId: "b" });
    expect(next.activePlanId).toBe("b");
    expect(next.plans).toEqual(before.plans);
  });

  it("activeSelected ignores unknown ids", () => {
    const before = state([plan("a", "A", true)], "a");
    expect(
      plansReducer(before, { type: "activeSelected", planId: "ghost" }),
    ).toBe(before);
  });

  it("switching between two plans keeps both lists intact (2 組切換保留)", () => {
    const two = state([plan("a", "A", true), plan("b", "B")], "a");
    const toB = plansReducer(two, { type: "activeSelected", planId: "b" });
    const backToA = plansReducer(toB, { type: "activeSelected", planId: "a" });
    expect(toB.plans).toEqual(two.plans);
    expect(backToA).toEqual(two);
  });
});

describe("plansReducer loaded reconciliation", () => {
  it("keeps the current active when it still exists, else falls to primary", () => {
    const before = state([], "b");
    const next = plansReducer(before, {
      type: "loaded",
      plans: [plan("a", "A", true), plan("b", "B")],
    });
    expect(next.activePlanId).toBe("b");
    const bounced = plansReducer(state([], "ghost"), {
      type: "loaded",
      plans: [plan("a", "A", true), plan("b", "B")],
    });
    expect(bounced.activePlanId).toBe("a");
  });

  it("yields no active id for an empty account", () => {
    const next = plansReducer(state([], null), { type: "loaded", plans: [] });
    expect(next.activePlanId).toBeNull();
    expect(hasPrimaryInvariant(next)).toBe(true);
  });
});

describe("plansReducer rename", () => {
  it("renames in place without touching primary flags", () => {
    const before = state([plan("a", "A", true), plan("b", "B")], "b");
    const next = plansReducer(before, { type: "renamed", planId: "b", name: "B+" });
    expect(next.plans[1]?.name).toBe("B+");
    expect(next.plans.map((p) => p.is_primary)).toEqual([true, false]);
  });
});
