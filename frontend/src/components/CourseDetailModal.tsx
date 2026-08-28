/**
 * CourseDetailModal: course identity card + live-scraped 教學大綱 sections.
 * Outline content comes from /api/courses/{id}/outline (public school page
 * scraped per click, 30-min cached) — school-origin text stays verbatim.
 */
import { useEffect, useState } from "react";
import { BoxArrowUpRight, InfoCircle, XLg } from "react-bootstrap-icons";

import { ApiError, fetchCourseOutline } from "../lib/api";
import type { CourseOut, CourseOutline } from "../lib/api";
import { useI18n } from "../lib/i18n";

interface CourseDetailModalProps {
  course: CourseOut;
  onClose: () => void;
}

function Section({ zh, en, value }: { zh: string; en: string; value: string | null }) {
  const { tx } = useI18n();
  if (value === null || value === "") return null;
  return (
    <div className="mb-3">
      <h3 className="h6 fw-bold text-teal-700 mb-1" style={{ fontSize: "0.85rem" }}>
        {tx(zh, en)}
      </h3>
      <p className="small text-dark mb-0" style={{ whiteSpace: "pre-wrap", lineHeight: 1.7 }}>
        {value}
      </p>
    </div>
  );
}

function MetaCell({ zh, en, value }: { zh: string; en: string; value: string | null }) {
  const { tx } = useI18n();
  if (value === null || value === "") return null;
  return (
    <div className="col-6 col-md-4 mb-2">
      <div className="text-muted" style={{ fontSize: "0.7rem" }}>{tx(zh, en)}</div>
      <div className="fw-semibold small text-dark">{value}</div>
    </div>
  );
}

function CourseDetailModal({ course, onClose }: CourseDetailModalProps) {
  const { tx } = useI18n();
  const [outline, setOutline] = useState<CourseOutline | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorText, setErrorText] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setErrorText(null);
    fetchCourseOutline(course.id, controller.signal)
      .then((body) => setOutline(body))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && err.status === 404) {
          setErrorText(tx("學校未提供此課大綱，或該課大綱暫時不存在。", "The school has no outline for this course (or it's missing right now)."));
        } else if (err instanceof ApiError && (err.status === 502 || err.status === 503)) {
          setErrorText(tx("學校大綱頁暫時無法讀取，請稍後再試。", "The school's outline page is unreachable right now. Please try again shortly."));
        } else {
          setErrorText(tx("讀取課程大綱失敗。", "Failed to load the course outline."));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [course.id, tx]);

  const name = course.name_zh ?? course.name_en ?? course.id;
  const hasOutline =
    outline !== null &&
    (outline.syllabus ?? outline.objectives ?? outline.teaching_methods ?? outline.evaluation ?? outline.references) !== null;

  return (
    <>
      <div className="crs-modal-backdrop" onClick={onClose} />
      <div className="crs-modal" role="dialog" aria-modal="true" aria-labelledby="course-detail-title">
        <div className="crs-modal-card card shadow-lg border-0 rounded-4" style={{ maxWidth: "44rem", width: "100%", maxHeight: "88vh", display: "flex", flexDirection: "column" }}>
          <div className="card-body p-4 d-flex flex-column min-h-0">
            <div className="d-flex align-items-start justify-content-between gap-2 mb-3">
              <div className="min-w-0">
                <h2 className="h5 fw-bold mb-1 text-dark text-truncate" id="course-detail-title">
                  {name}
                  {course.name_en !== null && course.name_zh !== null && (
                    <span className="text-muted fw-normal ms-2" style={{ fontSize: "0.8rem" }}>{course.name_en}</span>
                  )}
                </h2>
                <p className="text-muted small mb-0">
                  {tx("課程詳細資訊與教學大綱", "Course detail & syllabus")}
                  {course.code !== null && (
                    <span className="font-monospace ms-1">（{course.code}）</span>
                  )}
                </p>
              </div>
              <button
                type="button"
                className="btn btn-sm btn-outline-secondary rounded-circle p-1 flex-shrink-0"
                aria-label={tx("關閉", "Close")}
                onClick={onClose}
              >
                <XLg size={14} />
              </button>
            </div>

            <div className="row gx-3 mb-3">
              <MetaCell zh="系所" en="Department" value={course.dept} />
              <MetaCell zh="授課教師" en="Instructor" value={course.teacher} />
              <MetaCell
                zh="必選修"
                en="Required/Selected"
                value={tx(course.compulsory ? "必修" : "選修", course.compulsory ? "Required" : "Elective")}
              />
              <MetaCell
                zh="學分"
                en="Credits"
                value={course.credit !== null ? String(course.credit) : null}
              />
              <MetaCell
                zh="年級"
                en="Year"
                value={course.grade}
              />
              <MetaCell zh="班別" en="Class" value={course.class_} />
            </div>

            <div className="flex-grow-1 overflow-auto pe-1" style={{ minHeight: "6rem" }}>
              {loading ? (
                <p className="text-muted small mb-0 d-flex align-items-center gap-2">
                  <span className="spinner-border spinner-border-sm" aria-hidden />
                  <span>{tx("正在向學校讀取教學大綱…", "Fetching the syllabus from the school…")}</span>
                </p>
              ) : errorText !== null ? (
                <div className="alert alert-warning py-2 px-3 small rounded-3 mb-3" role="alert">
                  <InfoCircle size={13} className="me-1" />
                  {errorText}
                  {course.url !== null && (
                    <span className="d-block mt-1">
                      {tx("你仍可直接打開學校原始大綱頁：", "You can still open the school's original outline page:")}
                      <a href={course.url} target="_blank" rel="noopener noreferrer" className="ms-1 fw-semibold">
                        {tx("前往學校頁面", "Open school page")} <BoxArrowUpRight size={11} />
                      </a>
                    </span>
                  )}
                </div>
              ) : (
                <>
                  {outline !== null && outline.semester_title !== null && (
                    <p className="text-muted small mb-2 fst-italic">{outline.semester_title}</p>
                  )}
                  {hasOutline ? (
                    <>
                      <Section zh="課程大綱" en="Syllabus" value={outline?.syllabus ?? null} />
                      <Section zh="課程目標" en="Objectives" value={outline?.objectives ?? null} />
                      <Section zh="授課方式" en="Teaching methods" value={outline?.teaching_methods ?? null} />
                      <Section zh="評分方式" en="Evaluation" value={outline?.evaluation ?? null} />
                      <Section zh="參考書目" en="References" value={outline?.references ?? null} />
                    </>
                  ) : (
                    <div className="alert alert-info py-2 px-3 small rounded-3" role="status">
                      {tx("此課大綱頁無可解析內容；你可能需要直接查看學校原始頁。", "Nothing parseable on this course's outline page; you may need the school's original page instead.")}
                      {outline !== null && (
                        <span className="d-block mt-1">
                          <a href={outline.source_url} target="_blank" rel="noopener noreferrer" className="fw-semibold">
                            {tx("前往學校頁面", "Open school page")} <BoxArrowUpRight size={11} />
                          </a>
                        </span>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>

            {outline !== null && errorText === null && (
              <div className="text-muted border-top pt-2 mt-2" style={{ fontSize: "0.7rem" }}>
                {tx(`大綱擷取時間：${outline.fetched_at}`, `Outline fetched at: ${outline.fetched_at}`)}
                {" · "}
                <a href={outline.source_url} target="_blank" rel="noopener noreferrer">
                  {tx("學校原始頁", "School original")} <BoxArrowUpRight size={10} />
                </a>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

export default CourseDetailModal;
