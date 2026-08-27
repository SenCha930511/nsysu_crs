/**
 * Plans-list reducer (pure): mirrors the server's primary invariants for
 * optimistic UI between API round-trips. The invariant under test: whenever
 * the list is non-empty, EXACTLY ONE plan is primary; switching plans never
 * disturbs another plan's rows; the active id always names an existing plan.
 */

import type { PlanOut } from "./api";

export interface PlansListState {
  plans: PlanOut[];
  /** The plan the shared selection currently mirrors (null = none yet). */
  activePlanId: string | null;
}

export const INITIAL_PLANS_STATE: PlansListState = { plans: [], activePlanId: null };

export type PlansAction =
  | { type: "loaded"; plans: PlanOut[] }
  | { type: "created"; plan: PlanOut }
  | { type: "renamed"; planId: string; name: string }
  | { type: "removed"; planId: string; promotedPlanId: string | null }
  | { type: "primarySet"; planId: string }
  | { type: "activeSelected"; planId: string };

function pickActive(plans: PlanOut[], preferred: string | null): string | null {
  if (preferred !== null && plans.some((p) => p.id === preferred)) {
    return preferred;
  }
  const primary = plans.find((p) => p.is_primary);
  return (primary ?? plans[0] ?? null)?.id ?? null;
}

export function plansReducer(
  state: PlansListState,
  action: PlansAction,
): PlansListState {
  switch (action.type) {
    case "loaded":
      return {
        plans: action.plans,
        activePlanId: pickActive(action.plans, state.activePlanId),
      };
    case "created": {
      const plans = [...state.plans, action.plan];
      return { plans, activePlanId: action.plan.id };
    }
    case "renamed":
      return {
        ...state,
        plans: state.plans.map((p) =>
          p.id === action.planId ? { ...p, name: action.name } : p,
        ),
      };
    case "removed": {
      const doomed = state.plans.find((p) => p.id === action.planId);
      let plans = state.plans.filter((p) => p.id !== action.planId);
      if (doomed?.is_primary === true && plans.length > 0) {
        // Server promotes the oldest remaining; plans are oldest-first here.
        const promoted = action.promotedPlanId ?? plans[0]?.id;
        plans = plans.map((p) => ({ ...p, is_primary: p.id === promoted }));
      }
      const activePlanId =
        state.activePlanId === action.planId
          ? pickActive(plans, action.promotedPlanId)
          : pickActive(plans, state.activePlanId);
      return { plans, activePlanId };
    }
    case "primarySet":
      return {
        ...state,
        plans: state.plans.map((p) => ({ ...p, is_primary: p.id === action.planId })),
      };
    case "activeSelected":
      return state.plans.some((p) => p.id === action.planId)
        ? { ...state, activePlanId: action.planId }
        : state;
  }
}

/** Test/QA helper: the loading invariant in one boolean. */
export function hasPrimaryInvariant(state: PlansListState): boolean {
  if (state.plans.length === 0) return true;
  return state.plans.filter((p) => p.is_primary).length === 1;
}
