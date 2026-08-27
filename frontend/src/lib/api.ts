/**
 * Typed client for the read-only catalog API (plan todo 7):
 *   GET /api/courses      - paged course query with filters
 *   GET /api/catalog/meta - ingest health banner source
 * Anonymous read access; no auth headers. All other methods/endpoints are
 * out of scope for todo 10 (server plans/login arrive in todo 11).
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

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, detail: string) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
    ...(signal !== undefined ? { signal } : {}),
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body: unknown = await response.json();
      if (
        typeof body === "object" &&
        body !== null &&
        "detail" in body &&
        typeof (body as { detail: unknown }).detail === "string"
      ) {
        detail = (body as { detail: string }).detail;
      }
    } catch {
      // keep statusText
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

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
  return getJson<CoursePage>(`/api/courses?${qs}`, signal);
}

export function fetchCatalogMeta(signal?: AbortSignal): Promise<CatalogMeta> {
  return getJson<CatalogMeta>("/api/catalog/meta", signal);
}
