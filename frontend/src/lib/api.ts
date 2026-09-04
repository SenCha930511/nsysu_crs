/**
 * Typed client for the wrapper API:
 *   GET  /api/courses, /api/catalog/meta      - anonymous catalog reads (todo 7)
 *   POST /api/auth/login|logout, GET /api/auth/me - site session (todo 8)
 *   GET  /api/catalog/depts, /api/courses/{id}/outline - dept & syllabus reads
 *   GET  /api/me/selections, POST .../sync    - real selections (todo 9)
 *   GET  /api/stage                           - live school stage probe (todo 13)
 *   POST /api/write/preview|submit, GET /api/write/jobs/{id} - write flow (todo 14/15/16)
 *
 * CSRF (todo 14): every /api/write/* call must echo the login-response
 * csrf_token in the X-CSRF-Token header (the matching cookie is httpOnly,
 * so the body echo is the only JS-readable channel).
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

export interface CourseOutline {
  name_zh: string | null;
  code: string | null;
  name_en: string | null;
  course_type: string | null;
  requirement: string | null;
  dept: string | null;
  instructor: string | null;
  credit: string | null;
  semester_title: string | null;
  syllabus: string | null;
  objectives: string | null;
  teaching_methods: string | null;
  evaluation: string | null;
  references: string | null;
  source_url: string;
  fetched_at: string;
}

export interface CatalogDepts {
  departments: string[];
}

export function fetchCatalogDepts(signal?: AbortSignal): Promise<CatalogDepts> {
  return request<CatalogDepts>("/api/catalog/depts", signal !== undefined ? { signal } : {});
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
  /** Opaque CSRF token echoed from the login body; required on /api/write/*. */
  csrfToken?: string;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(path, {
    method: options.method ?? "GET",
    headers: {
      Accept: "application/json",
      ...(options.body !== undefined
        ? { "Content-Type": "application/json" }
        : {}),
      ...(options.csrfToken !== undefined
        ? { "X-CSRF-Token": options.csrfToken }
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

// ---------- selection schedule (anonymous; 選課日程 widget) ----------

export interface ScheduleEventDto {
  /** Stable id ("first_round_1" .. "confirmation"; "event_N" for new labels). */
  key: string;
  /** Verbatim school wording (display text in zh). */
  label: string;
  kind: "window" | "instant";
  /** ISO 8601 with +08:00 offset. */
  start: string;
  end: string | null;
}

export interface ScheduleResponse {
  /** False only with no snapshot AND a failed live fetch - hide the widget. */
  ok: boolean;
  /** Last-good snapshot served past freshness after a failed refresh. */
  stale: boolean;
  fetched_at: string | null;
  /** Verbatim school heading, e.g. 一佰一十五學年度第一學期選課日程. */
  title: string | null;
  events: ScheduleEventDto[];
}

export function fetchSchedule(signal?: AbortSignal): Promise<ScheduleResponse> {
  return request<ScheduleResponse>("/api/schedule", signal !== undefined ? { signal } : {});
}

export function fetchCourseOutline(
  courseId: string,
  signal?: AbortSignal,
): Promise<CourseOutline> {
  return request<CourseOutline>(
    `/api/courses/${courseId}/outline`,
    signal !== undefined ? { signal } : {},
  );
}

// ---------- ops posture (anonymous; todo 17 breaker banner seam) ----------

/** Public shape of GET /api/ops/state (gated admin fields are absent here). */
export interface OpsState {
  breaker: {
    /** "closed" | "open" | "half-open" */
    state: string;
    /** "normal" | "read-only" */
    mode: string;
    streak: number | null;
    opened_at: string | null;
    failure_threshold: number | null;
    recovery_after: number | null;
    probe_gate_seconds: number | null;
  };
  lockouts: { today: number; yesterday: number; total: number } | null;
}

export function fetchOpsState(signal?: AbortSignal): Promise<OpsState> {
  return request<OpsState>("/api/ops/state", signal !== undefined ? { signal } : {});
}

// ---------- auth (session cookie is httpOnly; fetch carries it same-origin) ----------

export interface LoginResponse {
  student_no: string;
  /** Double-submit CSRF token for /api/write/* (rotates on every login). */
  csrf_token: string;
}

export function login(
  studentNo: string,
  password: string,
): Promise<LoginResponse> {
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

// ---------- my selections (session-gated) ----------

export function fetchSelections(): Promise<SelectionsResponse> {
  return request("/api/me/selections");
}

export function syncSelections(): Promise<SelectionSyncResponse> {
  return request("/api/me/selections/sync", { method: "POST" });
}

// ---------- stage probe (session-gated; no CSRF - read-only) ----------

export interface StageInfo {
  /** "加退選" | "初選" | "關閉" | "未知" */
  stage: string;
  /** "ssform" | "stage5" | null (null when closed/unknown) */
  variant: string | null;
  params: Record<string, string> | null;
  need_confirmation: boolean;
  writable: boolean;
  /** Machine forensics: "ssform_link" | "closed_heading" | ... */
  reason: string;
  checked_at: string;
}

export function fetchStage(signal?: AbortSignal): Promise<StageInfo> {
  return request<StageInfo>("/api/stage", signal !== undefined ? { signal } : {});
}

// ---------- write flow (session + CSRF-gated; todo 14/15) ----------

export interface WriteOpIn {
  action: "+" | "-";
  /** Catalog UUID or 8-char school code (server resolves both). */
  course_id: string;
  /** Required for "+": int 1-20, unique within the batch. Forbidden for "-". */
  priority?: number | null;
  /** For "-": must exactly equal the resolved course's 8-char code. */
  drop_confirm_text?: string | null;
}

export interface QuotaOut {
  restrict: number | null;
  select_n: number | null;
  selected_n: number | null;
  remaining: number | null;
  ingested_at: string | null;
}

export interface OpVerdictOut {
  index: number;
  action: string;
  course_id: string;
  code: string | null;
  writable: boolean;
  /** "ok" | "無課號" | "同批加退混雜" | "不在已選" | "衝堂" */
  verdict: string;
  /** For 衝堂: the clashing code; else null. */
  detail: string | null;
  warnings: string[];
  quota: QuotaOut | null;
}

export interface PreviewResponse {
  stage: string;
  variant: string | null;
  form_url: string | null;
  writable: boolean;
  ops: OpVerdictOut[];
  warnings: string[];
  quota_as_of: string | null;
  payload: Record<string, string> | null;
  /** Single-use confirm token (5 min TTL); null when any op is blocked. */
  confirm_token: string | null;
  payload_hash: string | null;
  canonical_ops: string | null;
}

export interface SubmitResponse {
  job_id: string;
  status: string;
  payload_hash: string;
}

export interface JobOpOut {
  code: string;
  action: string;
  priority: number | null;
  /** Outcome enum or null while the audit row is still pending. */
  outcome: string | null;
  /** Verbatim school message (raw excerpt for parse_failed). */
  school_msg: string | null;
}

export interface JobView {
  job_id: string;
  /** queued | running | done | failed | cancelled | session_superseded */
  status: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  ops: JobOpOut[];
  message: string | null;
  /** "manual_resync_needed" when any op is unknown-reconciled. */
  reconcile: string | null;
}

export function previewWrite(
  ops: WriteOpIn[],
  csrfToken: string,
): Promise<PreviewResponse> {
  return request("/api/write/preview", {
    method: "POST",
    body: { ops },
    csrfToken,
  });
}

export function submitWrite(
  confirmToken: string,
  password: string,
  csrfToken: string,
): Promise<SubmitResponse> {
  return request("/api/write/submit", {
    method: "POST",
    body: { confirm_token: confirmToken, password },
    csrfToken,
  });
}

export function fetchWriteJob(
  jobId: string,
  csrfToken: string,
  signal?: AbortSignal,
): Promise<JobView> {
  return request(`/api/write/jobs/${jobId}`, {
    csrfToken,
    ...(signal !== undefined ? { signal } : {}),
  });
}

export interface JobsListResponse {
  jobs: JobView[];
}

export function fetchWriteJobs(csrfToken: string, limit = 30): Promise<JobView[]> {
  return request<JobsListResponse>(`/api/write/jobs?limit=${limit}`, { csrfToken }).then(
    (body) => body.jobs,
  );
}
