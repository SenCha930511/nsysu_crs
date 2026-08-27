/**
 * Typed client for the wrapper API:
 *   GET  /api/courses, /api/catalog/meta      - anonymous catalog reads (todo 7)
 *   POST /api/auth/login|logout, GET /api/auth/me - site session (todo 8)
 *   GET/POST/PATCH/DELETE /api/plans[...]     - multi-plan CRUD (todo 11)
 *   GET  /api/me/selections, POST .../sync    - real selections (todo 9)
 *
 * 401 policy seam: any non-login 401 means the site session is gone (or the
 * school jar expired - SELCRS_EXPIRED). The route layer registers one global
 * handler (soft logout + redirect to /login?reason=expired); it decides from
 * its own auth state whether the user was ever logged in, so a never-logged-in
 * visitor's 401 (e.g. the initial /api/auth/me probe) does not redirect.
 */

export interface CourseOut {
  id: string;
  year_sem: string;
  code: string | null;
  dept: string | null;
  grade: string | null;
  class_: string | null;
  name_zh: string | null;
  name_en: string | null;
  credit: number | null;
  compulsory: boolean;
  restrict: number | null;
  select_n: number | null;
  selected_n: number | null;
  remaining: number | null;
  teacher: string | null;
  room: string | null;
  /** 7-element Monday..Sunday array of period-code strings ("56"). */
  class_time: string[] | null;
  description: string | null;
  tags: string[] | null;
  english: boolean;
  change: string | null;
  change_desc: string | null;
  url: string | null;
  ingested_at: string;
}

export interface CoursePage {
  page: number;
  per_page: number;
  total: number;
  items: CourseOut[];
}

export interface CatalogMeta {
  ok: boolean;
  updated_at: string | null;
  row_count: number;
  source: string;
}

export interface CourseQuery {
  q?: string;
  dept?: string;
  grade?: string;
  credit?: number;
  compulsory?: boolean;
  english?: boolean;
  weekday?: number; // 1 (Mon) .. 7 (Sun)
  period?: string; // single period code, requires weekday
  page?: number; // 1-based, 50 rows per page (server-fixed)
}

export interface PlanOut {
  id: string;
  name: string;
  is_primary: boolean;
  item_count: number;
  created_at: string;
  updated_at: string | null;
}

export interface PlanItemOut {
  course_id: string;
  priority: number | null;
  added_at: string;
  /** Embedded catalog row; null for accepted-but-unknown ids. */
  course: CourseOut | null;
}

export interface SelectionItem {
  code: string | null;
  course_no: string | null;
  state: string;
  dept: string;
  name: string;
  credit: number | null;
  compulsory_elective: string;
  teacher: string;
  room_text: string;
  points_priority: number | null;
  stage: string;
  year_semest_note: string;
  times: string | null;
  room: string | null;
  unknown: boolean;
  course_id: string | null;
}

export interface SelectionsResponse {
  synced_at: string | null;
  items: SelectionItem[];
}

export interface SelectionSyncResponse {
  synced_at: string;
  added: SelectionItem[];
  removed: SelectionItem[];
  unchanged: SelectionItem[];
  items: SelectionItem[];
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  /** Extra fields from the error body (school_msg, retry_after_minutes, ...). */
  readonly extras: Record<string, unknown>;

  constructor(status: number, detail: string, extras: Record<string, unknown> = {}) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.extras = extras;
  }
}

export type UnauthorizedHandler = (detail: string, path: string) => void;

let unauthorizedHandler: UnauthorizedHandler | null = null;

export function bindUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(path, {
    method: options.method ?? "GET",
    headers: {
      Accept: "application/json",
      ...(options.body !== undefined
        ? { "Content-Type": "application/json" }
        : {}),
    },
    ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
    ...(options.signal !== undefined ? { signal: options.signal } : {}),
  });
  if (!response.ok) {
    let detail = response.statusText;
    let extras: Record<string, unknown> = {};
    try {
      const body: unknown = await response.json();
      if (typeof body === "object" && body !== null) {
        const record = body as Record<string, unknown>;
        if (typeof record.detail === "string") {
          detail = record.detail;
          const { detail: _dropped, ...rest } = record;
          extras = rest;
        }
      }
    } catch {
      // keep statusText
    }
    if (response.status === 401 && path !== "/api/auth/login") {
      unauthorizedHandler?.(detail, path);
    }
    throw new ApiError(response.status, detail, extras);
  }
  return (await response.json()) as T;
}

// ---------- catalog (anonymous) ----------

export function fetchCourses(
  query: CourseQuery,
  signal?: AbortSignal,
): Promise<CoursePage> {
  const params = new URLSearchParams();
  if (query.q !== undefined && query.q !== "") params.set("q", query.q);
  if (query.dept !== undefined && query.dept !== "") {
    params.set("dept", query.dept);
  }
  if (query.grade !== undefined && query.grade !== "") {
    params.set("grade", query.grade);
  }
  if (query.credit !== undefined) params.set("credit", String(query.credit));
  if (query.compulsory !== undefined) {
    params.set("compulsory", String(query.compulsory));
  }
  if (query.english !== undefined) {
    params.set("english", String(query.english));
  }
  if (query.weekday !== undefined) {
    params.set("weekday", String(query.weekday));
  }
  if (query.period !== undefined && query.period !== "") {
    params.set("period", query.period);
  }
  params.set("page", String(query.page ?? 1));
  const qs = params.toString();
  return request<CoursePage>(`/api/courses?${qs}`, signal !== undefined ? { signal } : {});
}

export function fetchCatalogMeta(signal?: AbortSignal): Promise<CatalogMeta> {
  return request<CatalogMeta>("/api/catalog/meta", signal !== undefined ? { signal } : {});
}

// ---------- auth (session cookie is httpOnly; fetch carries it same-origin) ----------

export function login(
  studentNo: string,
  password: string,
): Promise<{ student_no: string }> {
  return request("/api/auth/login", {
    method: "POST",
    body: { student_no: studentNo, password },
  });
}

export function logout(): Promise<{ ok: boolean }> {
  return request("/api/auth/logout", { method: "POST" });
}

export function fetchMe(signal?: AbortSignal): Promise<{ student_no: string }> {
  return request("/api/auth/me", signal !== undefined ? { signal } : {});
}

// ---------- plans (session-gated) ----------

export function fetchPlans(): Promise<PlanOut[]> {
  return request("/api/plans");
}

export function createPlan(name: string): Promise<PlanOut> {
  return request("/api/plans", { method: "POST", body: { name } });
}

export function patchPlan(
  planId: string,
  patch: { name?: string; is_primary?: boolean },
): Promise<PlanOut> {
  return request(`/api/plans/${planId}`, { method: "PATCH", body: patch });
}

export function deletePlan(
  planId: string,
): Promise<{ ok: boolean; promoted_plan_id: string | null }> {
  return request(`/api/plans/${planId}`, { method: "DELETE" });
}

export function fetchPlanItems(planId: string): Promise<PlanItemOut[]> {
  return request(`/api/plans/${planId}/items`);
}

export function putPlanItems(
  planId: string,
  items: { course_id: string; priority: number | null }[],
): Promise<PlanItemOut[]> {
  return request(`/api/plans/${planId}/items`, {
    method: "PUT",
    body: { items },
  });
}

// ---------- my selections (session-gated) ----------

export function fetchSelections(): Promise<SelectionsResponse> {
  return request("/api/me/selections");
}

export function syncSelections(): Promise<SelectionSyncResponse> {
  return request("/api/me/selections/sync", { method: "POST" });
}
