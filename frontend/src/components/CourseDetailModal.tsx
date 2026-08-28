/** CourseDetailModal: school-style outline sheet (bordered label/value rows
 * mirroring the school's own 課程教學大綱 table) inside a viewport-bounded,
 * independently scrollable card. Outline content comes from
 * /api/courses/{id}/outline — school-origin text stays verbatim. */
import { useEffect, useState } from "react";
import { BoxArrowUpRight, InfoCircle, XLg } from "react-bootstrap-icons";

import { ApiError, fetchCourseOutline } from "../lib/api";
import type { CourseOut, CourseOutline } from "../lib/api";
import { useI18n } from "../lib/i18n";

interface CourseDetailModalProps {
  course: CourseOut;
  onClose: () => void;
}

interface FieldRow {
  zh: string;
  en: string;
  value: string | null;
}

function SyllFieldRows({ rows }: { rows: FieldRow[] }) {
  const { lang } = useI18n();
  return (
    <>
      {rows
        .filter((row) => row.value !== null && row.value !== "")
        .map((row) => (
          <tr key={row.zh}>
            <td className="syll-label">
              {lang === "en" ? row.en : row.zh}
              <small>{lang === "en" ? row.zh : row.en}</small>
            </td>
            <td>{row.value}</td>
          </tr>
        ))}
    </>
  );
}

function SyllSection({ zh, en, value }: { zh: string; en: string; value: string | null }) {
  const { lang } = useI18n();
  if (value === null || value === "") return null;
  return (
    <tbody className="syll-section">
      <tr>
        <th colSpan={2}>{lang === "en" ? `${en}（${zh}）` : `${zh} ${en}`}</th>
      </tr>
      <tr>
        <td className="syll-content" colSpan={2}>
          {value}
        </td>
      </tr>
    </tbody>
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

  const fieldRows: FieldRow[] = [
    { zh: "中文名稱", en: "Course name (Chinese)", value: outline?.name_zh ?? course.name_zh },
    { zh: "英文名稱", en: "Course name (English)", value: outline?.name_en ?? course.name_en },
    { zh: "課號", en: "Course Code", value: outline?.code ?? course.code },
    { zh: "課程類別", en: "Type", value: outline?.course_type ?? null },
    {
      zh: "必選修",
      en: "Required/Selected",
      value: outline?.requirement ?? (course.compulsory ? "必修" : "選修"),
    },
    { zh: "系所", en: "Department", value: outline?.dept ?? course.dept },
    { zh: "授課教師", en: "Instructor", value: outline?.instructor ?? course.teacher },
    {
      zh: "學分",
      en: "Credit",
      value: outline?.credit ?? (course.credit !== null ? String(course.credit) : null),
    },
  ];

  return (
    <>
      <div className="crs-modal-backdrop" onClick={onClose} />
      <div className="crs-modal" role="dialog" aria-modal="true" aria-labelledby="course-detail-title">
        <div className="crs-modal-card card shadow-lg border-0 rounded-4 course-detail-card" style={{ maxWidth: "46rem", width: "100%" }}>
          <div className="course-detail-head card-body py-3 px-4">
            <div className="d-flex align-items-start justify-content-between gap-2">
              <div className="min-w-0">
                <h2 className="h5 fw-bold mb-0 text-dark" id="course-detail-title">
                  {name}
                </h2>
                <p className="text-muted mb-0" style={{ fontSize: "0.78rem" }}>
                  {tx("課程詳細資訊與教學大綱", "Course detail & syllabus")}
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
          </div>

          <div className="course-detail-scroll px-3 py-3">
            {loading ? (
              <p className="text-muted small mb-0 d-flex align-items-center gap-2 px-1 py-3">
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
                <table className="syll-table" role="presentation">
                  <thead>
                    <tr>
                      <th colSpan={2}>
                        {outline?.semester_title !== null && outline?.semester_title !== undefined
                          ? outline.semester_title
                          : tx("課程教學大綱", "Course syllabus")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <SyllFieldRows rows={fieldRows} />
                  </tbody>
                  {outline !== null && (
                    <>
                      <SyllSection zh="課程大綱" en="Course syllabus" value={outline.syllabus} />
                      <SyllSection zh="課程目標" en="Objectives" value={outline.objectives} />
                      <SyllSection zh="授課方式" en="Teaching methods" value={outline.teaching_methods} />
                      <SyllSection zh="評分方式" en="Evaluation (Criteria and ratio)" value={outline.evaluation} />
                      <SyllSection zh="參考書目" en="Reference book / textbook / documents" value={outline.references} />
                    </>
                  )}
                </table>

                {outline !== null && !hasOutline && (
                  <div className="alert alert-info py-2 px-3 small rounded-3 mt-3 mb-0" role="status">
                    {tx("此課大綱頁無可解析內容；你可能需要直接查看學校原始頁。", "Nothing parseable on this course's outline page; you may need the school's original page instead.")}
                    <span className="d-block mt-1">
                      <a href={outline.source_url} target="_blank" rel="noopener noreferrer" className="fw-semibold">
                        {tx("前往學校頁面", "Open school page")} <BoxArrowUpRight size={11} />
                      </a>
                    </span>
                  </div>
                )}

                {outline !== null && (
                  <div className="text-muted mt-2 px-1" style={{ fontSize: "0.7rem" }}>
                    {tx(`大綱擷取時間：${outline.fetched_at}`, `Outline fetched at: ${outline.fetched_at}`)}
                    {" · "}
                    <a href={outline.source_url} target="_blank" rel="noopener noreferrer">
                      {tx("學校原始頁", "School original")} <BoxArrowUpRight size={10} />
                    </a>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

export default CourseDetailModal;
