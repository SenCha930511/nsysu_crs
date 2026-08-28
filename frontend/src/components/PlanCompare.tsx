/** PlanCompare: head-to-head lab view for two plans — totals, clashes,
 * shared courses with both priorities, and per-side unique courses (fetches
 * items on demand from /api/plans/{id}/items). */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Award, Book, Clock, ExclamationTriangleFill, Layers } from "react-bootstrap-icons";

import { fetchPlanItems } from "../lib/api";
import type { CourseOut, PlanItemOut, PlanOut } from "../lib/api";
import { conflictPairs } from "../lib/conflicts";
import { useI18n } from "../lib/i18n";
import { totalCreditsAndHours } from "../lib/totals";

interface PlanCompareProps {
  plans: PlanOut[];
  defaultA: string | null;
}

interface PlanSide {
  items: PlanItemOut[];
  courses: CourseOut[];
  credits: number;
  hours: number;
  clashes: number;
}

interface CompareRow {
  name: string;
  dept: string | null;
  priorityA: number | null;
  priorityB: number | null;
}

function knownCourses(items: PlanItemOut[]): CourseOut[] {
  return items.map((item) => item.course).filter((c): c is CourseOut => c !== null);
}

function toSide(items: PlanItemOut[]): PlanSide {
  const courses = knownCourses(items);
  const slotted = courses.filter((c) => c.class_time !== null);
  const totals = totalCreditsAndHours(slotted);
  return {
    items,
    courses,
    credits: totals.totalCredits,
    hours: totals.totalHours,
    clashes: conflictPairs(slotted).length,
  };
}

function StatStrip({ side, label }: { side: PlanSide; label: string }) {
  const { tx } = useI18n();
  return (
    <div className="badge text-bg-light border d-inline-flex align-items-center gap-2 px-2.5 py-1.5" style={{ fontSize: "0.78rem" }}>
      <strong className="text-teal-700">{label}</strong>
      <span className="d-inline-flex align-items-center gap-1"><Book size={11} />{side.courses.length}{tx(" 門", "")}</span>
      <span className="d-inline-flex align-items-center gap-1"><Award size={11} />{side.credits}{tx(" 學分", " cr")}</span>
      <span className="d-inline-flex align-items-center gap-1"><Clock size={11} />{side.hours}{tx(" 節", " hrs")}</span>
      {side.clashes > 0 && (
        <span className="d-inline-flex align-items-center gap-1 text-danger"><ExclamationTriangleFill size={11} />{tx(`衝堂 ${side.clashes} 組`, `${side.clashes} clash(es)`)}</span>
      )}
    </div>
  );
}

function RowList({ title, rows, tone }: { title: string; rows: CompareRow[]; tone: "primary" | "danger" | "success" }) {
  const { tx } = useI18n();
  if (rows.length === 0) return null;
  const badge =
    tone === "primary" ? "text-bg-primary" : tone === "danger" ? "text-bg-danger" : "text-bg-success";
  return (
    <div className="mb-3">
      <div className="small fw-bold mb-1 text-muted">{title}（{rows.length}）</div>
      <ul className="small mb-0 ps-3" aria-label={tx(`${title} 清單`, `${title} list`)}>
        {rows.map((row) => (
          <li key={`${title}-${row.name}`} className="mb-1">
            <span className={`badge ${badge} me-1`} style={{ fontSize: "0.66rem" }}>
              {row.priorityA !== null ? `A=${row.priorityA}` : ""}
              {row.priorityA !== null && row.priorityB !== null ? " · " : ""}
              {row.priorityB !== null ? `B=${row.priorityB}` : ""}
            </span>
            <span className="fw-semibold text-dark">{row.name}</span>
            {row.dept !== null && <span className="text-muted ms-1">{row.dept}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function PlanCompare({ plans, defaultA }: PlanCompareProps) {
  const { lang, tx } = useI18n();
  const [idA, setIdA] = useState<string | null>(defaultA ?? plans[0]?.id ?? null);
  const [idB, setIdB] = useState<string | null>(
    plans.find((plan) => plan.id !== (defaultA ?? plans[0]?.id))?.id ?? null,
  );
  const [sideA, setSideA] = useState<PlanSide | null>(null);
  const [sideB, setSideB] = useState<PlanSide | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);

  const loadSide = useCallback(async (planId: string): Promise<PlanSide> => {
    const items = await fetchPlanItems(planId);
    return toSide(items);
  }, []);

  useEffect(() => {
    if (idA === null || idB === null || idA === idB) {
      setSideA(null);
      setSideB(null);
      return;
    }
    let alive = true;
    setLoading(true);
    setErrorText(null);
    Promise.all([loadSide(idA), loadSide(idB)])
      .then(([a, b]) => {
        if (!alive) return;
        setSideA(a);
        setSideB(b);
      })
      .catch(() => {
        if (alive) setErrorText(tx("比較資料讀取失敗，請稍後再試。", "Failed to load comparison data. Please try again shortly."));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [idA, idB, loadSide, tx]);

  const diff = useMemo(() => {
    if (sideA === null || sideB === null) return null;
    const nameOf = (course: CourseOut | null, id: string) => course?.name_zh ?? course?.name_en ?? id;
    const mapA = new Map(sideA.items.map((item) => [item.course_id, item]));
    const mapB = new Map(sideB.items.map((item) => [item.course_id, item]));
    const shared: CompareRow[] = [];
    const onlyA: CompareRow[] = [];
    const onlyB: CompareRow[] = [];
    for (const [courseId, itemA] of mapA.entries()) {
      const hitB = mapB.get(courseId);
      const name = nameOf(itemA.course, courseId);
      const dept = itemA.course?.dept ?? hitB?.course?.dept ?? null;
      if (hitB !== undefined) {
        shared.push({ name, dept, priorityA: itemA.priority, priorityB: hitB.priority });
      } else {
        onlyA.push({ name, dept, priorityA: itemA.priority, priorityB: null });
      }
    }
    for (const [courseId, itemB] of mapB.entries()) {
      if (!mapA.has(courseId)) {
        onlyB.push({ name: nameOf(itemB.course, courseId), dept: itemB.course?.dept ?? null, priorityA: null, priorityB: itemB.priority });
      }
    }
    const byName = (x: CompareRow, y: CompareRow) => x.name.localeCompare(y.name, lang === "zh" ? "zh-Hant" : "en");
    return { shared: shared.sort(byName), onlyA: onlyA.sort(byName), onlyB: onlyB.sort(byName) };
  }, [sideA, sideB, lang]);

  const planA = plans.find((p) => p.id === idA) ?? null;
  const planB = plans.find((p) => p.id === idB) ?? null;

  return (
    <div className="card shadow-sm border-0 rounded-4 mb-4" data-testid="plan-compare-panel">
      <div className="card-body p-4">
        <div className="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-3">
          <h2 className="h6 fw-bold mb-0 text-dark d-flex align-items-center gap-2">
            <Layers className="text-teal-600" size={16} />
            <span>{tx("方案對比", "Plan comparison")}</span>
          </h2>
          <div className="d-flex align-items-center gap-2 flex-wrap">
            <select
              className="form-select form-select-sm rounded-pill"
              style={{ width: "auto" }}
              value={idA ?? ""}
              aria-label={tx("對比的左側方案", "Left plan of the comparison")}
              onChange={(e) => setIdA(e.target.value)}
            >
              {plans.map((plan) => (
                <option key={plan.id} value={plan.id}>{plan.name}</option>
              ))}
            </select>
            <span className="text-muted small">vs</span>
            <select
              className="form-select form-select-sm rounded-pill"
              style={{ width: "auto" }}
              value={idB ?? ""}
              aria-label={tx("對比的右側方案", "Right plan of the comparison")}
              onChange={(e) => setIdB(e.target.value)}
            >
              {plans.map((plan) => (
                <option key={plan.id} value={plan.id}>{plan.name}</option>
              ))}
            </select>
          </div>
        </div>

        {idA === idB ? (
          <p className="text-muted small mb-0 bg-light rounded-3 p-3 text-center">
            {tx("選兩組不同的方案即可對比差異（共同課、僅此有、志願序差異、衝堂/學分/節數對照）。", "Pick two different plans to see what they share, what's unique to each, priority differences, plus clash/credit/hour totals.")}
          </p>
        ) : loading ? (
          <p className="text-muted small mb-0 bg-light rounded-3 p-3 text-center">{tx("讀取兩組方案中…", "Loading both plans…")}</p>
        ) : errorText !== null ? (
          <div className="alert alert-danger py-1.5 px-3 small rounded-3 mb-0" role="alert">{errorText}</div>
        ) : sideA !== null && sideB !== null && diff !== null ? (
          <>
            <div className="d-flex flex-wrap gap-2 mb-3">
              <StatStrip side={sideA} label={tx(`A・${planA?.name ?? ""}`, `A: ${planA?.name ?? ""}`)} />
              <StatStrip side={sideB} label={tx(`B・${planB?.name ?? ""}`, `B: ${planB?.name ?? ""}`)} />
            </div>
            <RowList title={tx("兩邊都有的課（志願序對照）", "Courses in both (priority check)")} rows={diff.shared} tone="success" />
            <RowList title={tx("僅 A 有", "Only in A")} rows={diff.onlyA} tone="primary" />
            <RowList title={tx("僅 B 有", "Only in B")} rows={diff.onlyB} tone="danger" />
            {diff.shared.length === 0 && diff.onlyA.length === 0 && diff.onlyB.length === 0 && (
              <p className="text-muted small mb-0 bg-light rounded-3 p-3 text-center">{tx("兩組方案都沒有課程。", "Both plans are empty.")}</p>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}

export default PlanCompare;
