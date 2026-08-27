/**
 * Plans sync engine (todo 11): binds the shared selection state (todo 10
 * seam) to the session-gated plans API.
 *
 * - Login -> list plans -> active = stored choice (if still valid) else the
 *   PRIMARY plan -> its items hydrate the selection via a SILENT replace
 *   (no echo PUT).
 * - User edits (add/remove in the browser, priority edits in /plans) ->
 *   debounced PUT replace-all back to the ACTIVE plan.
 * - Logout -> the plan view is wiped from the grid and localStorage (a
 *   server plan must not linger on a shared device).
 * - Priority map lives HERE (the server is the authority on read; this
 *   provider is the authority between writes). Unknown (non-catalog) course
 *   ids hydrate as placeholder CourseOut rows so the grid can render and
 *   remove them.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";

import {
  createPlan,
  deletePlan,
  fetchPlanItems,
  fetchPlans,
  patchPlan,
  putPlanItems,
} from "../lib/api";
import type { CourseOut, PlanOut } from "../lib/api";
import {
  applyPriorityEdit,
  assignSequentialPriority,
  orderIdsByPriority,
} from "../lib/priority";
import type { PriorityEditResult, PriorityMap } from "../lib/priority";
import { plansReducer, INITIAL_PLANS_STATE } from "../lib/plansState";
import { SELECTION_CHANGED_EVENT, useSelection } from "./selection";
import { useAuth } from "./auth";

const ACTIVE_PLAN_STORAGE_KEY = "nsysu_crs_active_plan";
const WRITE_DEBOUNCE_MS = 700;

function placeholderCourse(courseId: string): CourseOut {
  return {
    id: courseId,
    year_sem: "",
    code: null,
    dept: null,
    grade: null,
    class_: null,
    name_zh: "未知課程（已不在課目錄）",
    name_en: null,
    credit: null,
    compulsory: false,
    restrict: null,
    select_n: null,
    selected_n: null,
    remaining: null,
    teacher: null,
    room: null,
    class_time: null,
    description: null,
    tags: null,
    english: false,
    change: null,
    change_desc: null,
    url: null,
    ingested_at: "",
  };
}

export interface PlanListItem {
  courseId: string;
  priority: number | null;
  course: CourseOut | null;
  known: boolean;
}

export interface PlansSyncContextValue {
  plans: PlanOut[];
  activePlanId: string | null;
  /** True once the active plan's items have landed in the selection. */
  hydrated: boolean;
  /** True while a PUT write-back is in flight. */
  saving: boolean;
  error: string | null;
  /** Active-plan rows in display order (priority asc, nulls last). */
  orderedItems: PlanListItem[];
  knownCourseIds: ReadonlySet<string>;
  selectPlan: (planId: string) => Promise<void>;
  createAndSelect: (name: string) => Promise<void>;
  rename: (planId: string, name: string) => Promise<void>;
  remove: (planId: string) => Promise<void>;
  setPrimary: (planId: string) => Promise<void>;
  /** Drag-drop result: full new display order -> priorities 1..N / null. */
  applyDragOrder: (orderedIds: string[]) => void;
  /** Manual priority edit; resolves with the rule outcome. */
  editPriority: (courseId: string, rawValue: string) => PriorityEditResult;
}

const PlansSyncContext = createContext<PlansSyncContextValue | null>(null);

function readStoredActivePlan(): string | null {
  try {
    return localStorage.getItem(ACTIVE_PLAN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeActivePlan(planId: string | null): void {
  try {
    if (planId === null) {
      localStorage.removeItem(ACTIVE_PLAN_STORAGE_KEY);
    } else {
      localStorage.setItem(ACTIVE_PLAN_STORAGE_KEY, planId);
    }
  } catch {
    // localStorage unavailable: active plan is per-load only
  }
}

export function PlansSyncProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const { selected, replace } = useSelection();

  const [listState, dispatch] = useReducer(plansReducer, INITIAL_PLANS_STATE);
  const [priorities, setPriorities] = useState<PriorityMap>({});
  const [knownCourseIds, setKnownCourseIds] = useState<ReadonlySet<string>>(
    new Set(),
  );
  const [hydrated, setHydrated] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const saveTimer = useRef<number | null>(null);
  const writeSeq = useRef(0);
  const stateRef = useRef({ priorities, activePlanId: listState.activePlanId });
  stateRef.current = { priorities, activePlanId: listState.activePlanId };
  const selectedRef = useRef(selected);
  selectedRef.current = selected;

  const hydratePlan = useCallback(
    async (planId: string, seq: number) => {
      const items = await fetchPlanItems(planId);
      if (seq !== writeSeq.current) return; // superseded while in flight
      const nextPriorities: PriorityMap = {};
      const nextKnown = new Set<string>();
      const courses: CourseOut[] = [];
      for (const item of items) {
        nextPriorities[item.course_id] = item.priority;
        if (item.course !== null) {
          nextKnown.add(item.course_id);
          courses.push(item.course);
        } else {
          courses.push(placeholderCourse(item.course_id));
        }
      }
      setPriorities(nextPriorities);
      setKnownCourseIds(nextKnown);
      setHydrated(true);
      // Course order on the grid mirrors item order; silent = no echo PUT.
      replace(courses, { silent: true });
    },
    [replace],
  );

  const boot = useCallback(async () => {
    try {
      const plans = await fetchPlans();
      dispatch({ type: "loaded", plans });
      const stored = readStoredActivePlan();
      const active =
        plans.find((p) => p.id === stored)?.id ??
        plans.find((p) => p.is_primary)?.id ??
        plans[0]?.id ??
        null;
      if (active !== null) {
        if (stored !== active) storeActivePlan(active);
        await hydratePlan(active, writeSeq.current);
      } else {
        setHydrated(true);
      }
      setError(null);
    } catch (err) {
      console.error("plans boot failed:", err);
      setError(err instanceof Error ? err.message : String(err));
      setHydrated(true); // degrade to local-only selection
    }
  }, [hydratePlan]);

  const reset = useCallback(() => {
    writeSeq.current += 1;
    dispatch({ type: "loaded", plans: [] });
    setPriorities({});
    setKnownCourseIds(new Set());
    setHydrated(false);
    setSaving(false);
    setError(null);
    storeActivePlan(null);
    replace([], { silent: true });
  }, [replace]);

  useEffect(() => {
    if (auth.status === "authed") {
      writeSeq.current += 1;
      void boot();
    } else if (auth.status === "anon") {
      reset();
    }
  }, [auth.status, boot, reset]);

  // ---------- optimistic write-back (any selection change) ----------

  const scheduleWrite = useCallback(() => {
    const { activePlanId } = stateRef.current;
    if (activePlanId === null) return;
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    const seq = (writeSeq.current += 1);
    saveTimer.current = window.setTimeout(() => {
      const { priorities: prio } = stateRef.current;
      const body = selectedRef.current.map((course) => ({
        course_id: course.id,
        priority: prio[course.id] ?? null,
      }));
      setSaving(true);
      putPlanItems(activePlanId, body)
        .then((items) => {
          if (seq !== writeSeq.current) return;
          setSaving(false);
          setError(null);
          // Server is the authority: unknown joins lose their known flag again.
          setKnownCourseIds(
            new Set(
              items.filter((item) => item.course !== null).map((i) => i.course_id),
            ),
          );
        })
        .catch((err: unknown) => {
          if (seq !== writeSeq.current) return;
          setSaving(false);
          console.error("plan write-back failed:", err);
          setError(err instanceof Error ? err.message : String(err));
        });
    }, WRITE_DEBOUNCE_MS);
  }, []);

  useEffect(() => {
    const onChanged = () => {
      if (!hydrated) return;
      scheduleWrite();
    };
    window.addEventListener(SELECTION_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(SELECTION_CHANGED_EVENT, onChanged);
  }, [hydrated, scheduleWrite]);

  useEffect(
    () => () => {
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    },
    [],
  );

  // ---------- plan CRUD (optimistic + server reconcile) ----------

  const selectPlan = useCallback(
    async (planId: string) => {
      if (planId === stateRef.current.activePlanId) return;
      writeSeq.current += 1;
      dispatch({ type: "activeSelected", planId });
      storeActivePlan(planId);
      setHydrated(false);
      await hydratePlan(planId, writeSeq.current);
    },
    [hydratePlan],
  );

  const createAndSelect = useCallback(
    async (name: string) => {
      const plan = await createPlan(name);
      writeSeq.current += 1;
      dispatch({ type: "created", plan });
      storeActivePlan(plan.id);
      setPriorities({});
      setKnownCourseIds(new Set());
      setHydrated(true);
      replace([], { silent: true });
    },
    [replace],
  );

  const rename = useCallback(async (planId: string, name: string) => {
    const updated = await patchPlan(planId, { name });
    dispatch({ type: "renamed", planId, name: updated.name });
  }, []);

  const removePlan = useCallback(
    async (planId: string) => {
      const wasActive = planId === stateRef.current.activePlanId;
      const result = await deletePlan(planId);
      dispatch({
        type: "removed",
        planId,
        promotedPlanId: result.promoted_plan_id,
      });
      const remaining = await fetchPlans();
      dispatch({ type: "loaded", plans: remaining });
      if (!wasActive) return;
      writeSeq.current += 1;
      const promoted = result.promoted_plan_id;
      const nextId =
        (promoted !== null && remaining.some((p) => p.id === promoted)
          ? promoted
          : null) ??
        remaining.find((p) => p.is_primary)?.id ??
        remaining[0]?.id ??
        null;
      storeActivePlan(nextId);
      if (nextId !== null) {
        setHydrated(false);
        await hydratePlan(nextId, writeSeq.current);
      } else {
        setPriorities({});
        setKnownCourseIds(new Set());
        setHydrated(true);
        replace([], { silent: true });
      }
    },
    [hydratePlan, replace],
  );

  const setPrimary = useCallback(async (planId: string) => {
    await patchPlan(planId, { is_primary: true });
    dispatch({ type: "primarySet", planId });
  }, []);

  // ---------- priority editing ----------

  const applyDragOrder = useCallback(
    (orderedIds: string[]) => {
      setPriorities(assignSequentialPriority(orderedIds));
      scheduleWrite();
    },
    [scheduleWrite],
  );

  const editPriority = useCallback(
    (courseId: string, rawValue: string): PriorityEditResult => {
      const orderedIds = orderIdsByPriority(
        selectedRef.current.map((c) => c.id),
        stateRef.current.priorities,
      );
      const { priorities: next, result } = applyPriorityEdit(
        stateRef.current.priorities,
        courseId,
        rawValue,
        orderedIds,
      );
      if (result.ok) {
        setPriorities(next);
        scheduleWrite();
        setError(null);
      } else {
        setError(
          result.error === "priority_duplicate"
            ? "志願序不可重複"
            : "志願序須為 1–20 的整數",
        );
      }
      return result;
    },
    [scheduleWrite],
  );

  const orderedItems = useMemo<PlanListItem[]>(() => {
    const byId = new Map(selected.map((course) => [course.id, course]));
    const orderedIds = orderIdsByPriority(
      selected.map((c) => c.id),
      priorities,
    );
    return orderedIds.map((id) => ({
      courseId: id,
      priority: priorities[id] ?? null,
      course: byId.get(id) ?? null,
      known: knownCourseIds.has(id),
    }));
  }, [selected, priorities, knownCourseIds]);

  const value = useMemo<PlansSyncContextValue>(
    () => ({
      plans: listState.plans,
      activePlanId: listState.activePlanId,
      hydrated,
      saving,
      error,
      orderedItems,
      knownCourseIds,
      selectPlan,
      createAndSelect,
      rename,
      remove: removePlan,
      setPrimary,
      applyDragOrder,
      editPriority,
    }),
    [
      listState,
      hydrated,
      saving,
      error,
      orderedItems,
      knownCourseIds,
      selectPlan,
      createAndSelect,
      rename,
      removePlan,
      setPrimary,
      applyDragOrder,
      editPriority,
    ],
  );

  return (
    <PlansSyncContext.Provider value={value}>
      {children}
    </PlansSyncContext.Provider>
  );
}

export function usePlansSync(): PlansSyncContextValue {
  const ctx = useContext(PlansSyncContext);
  if (ctx === null) {
    throw new Error("usePlansSync must be used inside PlansSyncProvider");
  }
  return ctx;
}
