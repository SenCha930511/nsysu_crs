/**
 * /plans: multi-plan CRUD + 志願序 (priority 1..20) editing.
 *
 * Left: plan list (create / switch-active / rename / delete / set-primary).
 * The active plan mirrors the shared selection, so the home grid follows it.
 * Right: the active plan as a dnd-kit sortable list; dragging assigns
 * priority 1..N by position (past 20 falls back to unprioritized), manual
 * number edits accept 1..20 unique values and REJECT duplicates/out-of-range.
 * All edits autosave (replace-all PUT) via the plans-sync provider.
 */

import { useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import type { DragEndEvent } from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  ArrowRepeat,
  Calendar3,
  CalendarCheck,
  Download,
  GripVertical,
  Pencil,
  PlusLg,
  Star,
  StarFill,
  Trash3,
} from "react-bootstrap-icons";

import type { CourseOut } from "../lib/api";
import { ApiError } from "../lib/api";
import { downloadGridPng, downloadPlanIcs, icsErrorMessage } from "../lib/export";
import ScheduleTable from "../components/ScheduleTable";
import type { PlanListItem, PlansSyncContextValue } from "../state/plansSync";
import { usePlansSync } from "../state/plansSync";
import { useSelection } from "../state/selection";

function SortablePriorityRow({
  item,
  onEditPriority,
  onRemove,
}: {
  item: PlanListItem;
  onEditPriority: (raw: string) => void;
  onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: item.courseId });
  const name = item.course?.name_zh ?? item.course?.name_en ?? item.courseId;
  const meta = [item.course?.dept, item.course?.teacher]
    .filter((part) => part !== null && part !== "")
    .join(" · ");

  return (
    <div
      ref={setNodeRef}
      className={`priority-row${isDragging ? " priority-row-dragging" : ""}`}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      data-course-id={item.courseId}
    >
      <button
        type="button"
        className="drag-handle"
        aria-label={`拖曳排序 ${name}`}
        {...attributes}
        {...listeners}
      >
        <GripVertical size={16} />
      </button>
      <input
        key={`${item.courseId}:${item.priority ?? "null"}`}
        type="text"
        inputMode="numeric"
        className="form-control form-control-sm priority-input"
        defaultValue={item.priority === null ? "" : String(item.priority)}
        placeholder="–"
        aria-label={`志願序 ${name}`}
        onBlur={(e) => onEditPriority(e.currentTarget.value)}
        onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
          if (e.key === "Enter") e.currentTarget.blur();
        }}
      />
      <div className="priority-row-main">
        <span className="fw-semibold text-dark">{name}</span>
        {!item.known && (
          <span className="badge text-bg-secondary ms-1">目錄查無此課</span>
        )}
        {meta !== "" && <div className="text-muted small">{meta}</div>}
      </div>
      <button
        type="button"
        className="btn btn-sm btn-outline-danger d-flex align-items-center justify-content-center p-1.5 rounded-2"
        aria-label={`從課表移除 ${name}`}
        onClick={onRemove}
      >
        <Trash3 size={13} />
      </button>
    </div>
  );
}

function PlanListSidebar({ sync }: { sync: PlansSyncContextValue }) {
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [icsBusyId, setIcsBusyId] = useState<string | null>(null);

  const onIcs = (planId: string) => {
    if (icsBusyId !== null) return;
    setIcsBusyId(planId);
    setActionError(null);
    downloadPlanIcs(planId)
      .catch((err: unknown) =>
        setActionError(
          err instanceof ApiError ? icsErrorMessage(err) : String(err),
        ),
      )
      .finally(() => setIcsBusyId(null));
  };

  const onCreate = (event: FormEvent) => {
    event.preventDefault();
    const name = newName.trim();
    if (name === "" || creating) return;
    setCreating(true);
    setActionError(null);
    sync
      .createAndSelect(name)
      .then(() => setNewName(""))
      .catch((err: unknown) =>
        setActionError(err instanceof Error ? err.message : String(err)),
      )
      .finally(() => setCreating(false));
  };

  const commitRename = (planId: string) => {
    const name = renameValue.trim();
    setRenamingId(null);
    if (name === "") return;
    sync.rename(planId, name).catch((err: unknown) => {
      setActionError(err instanceof Error ? err.message : String(err));
    });
  };

  return (
    <div className="card shadow-sm border-0 rounded-4 mb-3">
      <div className="card-body p-3.5">
        <h2 className="h6 fw-bold mb-3 d-flex align-items-center gap-1.5">
          <CalendarCheck className="text-teal-600" size={16} />
          <span>我的課表組合</span>
        </h2>
        <form className="input-group input-group-sm mb-3" onSubmit={onCreate}>
          <input
            type="text"
            className="form-control"
            placeholder="新課表名稱（如：志願A）"
            aria-label="新課表名稱"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <button type="submit" className="btn btn-brand d-inline-flex align-items-center gap-1" disabled={creating}>
            <PlusLg size={13} />
            <span>新增</span>
          </button>
        </form>
        {actionError !== null && (
          <div className="alert alert-danger py-1.5 px-3 small rounded-3 mb-2" role="alert">
            {actionError}
          </div>
        )}
        {sync.plans.length === 0 && (
          <p className="text-muted small mb-0 p-2 text-center bg-light rounded-3">
            尚無課表。建立第一組後，挑課會自動存入該組。
          </p>
        )}
        <div className="d-flex flex-column gap-1">
          {sync.plans.map((plan) => {
            const active = plan.id === sync.activePlanId;
            return (
              <div
                key={plan.id}
                className={`plan-row${active ? " plan-row-active" : ""}`}
                data-plan-id={plan.id}
              >
                <button
                  type="button"
                  className="btn btn-sm p-1 border-0"
                  aria-label={
                    plan.is_primary ? `主課表 ${plan.name}` : `設為主課表 ${plan.name}`
                  }
                  title={plan.is_primary ? "主課表" : "設為主課表"}
                  onClick={() => {
                    if (!plan.is_primary) {
                      sync.setPrimary(plan.id).catch((err: unknown) => {
                        setActionError(
                          err instanceof Error ? err.message : String(err),
                        );
                      });
                    }
                  }}
                >
                  {plan.is_primary ? (
                    <StarFill className="text-warning" size={15} />
                  ) : (
                    <Star className="text-muted" size={15} />
                  )}
                </button>
                {renamingId === plan.id ? (
                  <input
                    type="text"
                    className="form-control form-control-sm"
                    defaultValue={plan.name}
                    aria-label={`改名 ${plan.name}`}
                    autoFocus
                    onChange={(e) => setRenameValue(e.target.value)}
                    onBlur={() => commitRename(plan.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") commitRename(plan.id);
                      if (e.key === "Escape") setRenamingId(null);
                    }}
                  />
                ) : (
                  <button
                    type="button"
                    className={`btn btn-sm plan-switch${
                      active ? " fw-bold text-teal-800" : ""
                    }`}
                    onClick={() => void sync.selectPlan(plan.id)}
                  >
                    {plan.name}
                    <span className="badge text-bg-light border ms-1 font-monospace">
                      {plan.item_count}
                    </span>
                  </button>
                )}
                {plan.is_primary && (
                  <span className="badge bg-teal-100 text-teal-800 border border-teal-200">主</span>
                )}
                <span className="ms-auto d-flex align-items-center gap-1">
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-secondary p-1 px-1.5 rounded-2"
                    title="下載 ICS（匯入 Google 日曆等）"
                    disabled={icsBusyId !== null}
                    onClick={() => onIcs(plan.id)}
                  >
                    {icsBusyId === plan.id ? "…" : "ICS"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-secondary p-1 px-1.5 rounded-2"
                    title="重新命名"
                    onClick={() => {
                      setRenamingId(plan.id);
                      setRenameValue(plan.name);
                    }}
                  >
                    <Pencil size={11} />
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-danger p-1 px-1.5 rounded-2"
                    title="刪除課表"
                    onClick={() => {
                      if (
                        window.confirm(
                          `確定刪除「${plan.name}」？其中 ${plan.item_count} 門課程紀錄將一併移除。`,
                        )
                      ) {
                        sync.remove(plan.id).catch((err: unknown) => {
                          setActionError(
                            err instanceof Error ? err.message : String(err),
                          );
                        });
                      }
                    }}
                  >
                    <Trash3 size={11} />
                  </button>
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function ActivePlanEditor({ sync }: { sync: PlansSyncContextValue }) {
  const { remove } = useSelection();
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const onDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (over === null || active.id === over.id) return;
    const ids = sync.orderedItems.map((item) => item.courseId);
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from === -1 || to === -1) return;
    sync.applyDragOrder(arrayMove(ids, from, to));
  };

  const activePlan = sync.plans.find((p) => p.id === sync.activePlanId) ?? null;

  return (
    <div className="card shadow-sm border-0 rounded-4 mb-3">
      <div className="card-body p-3.5">
        <div className="d-flex align-items-center justify-content-between mb-1">
          <h2 className="h6 fw-bold mb-0">
            {activePlan !== null ? `「${activePlan.name}」志願序` : "志願序"}
          </h2>
          {activePlan !== null && (
            <span className="badge text-bg-light border text-muted" role="status">
              {sync.saving ? "儲存中…" : "已自動儲存"}
            </span>
          )}
        </div>
        <p className="text-muted small mb-3">
          拖曳調整順序（自動編號 1…N），或直接輸入 1–20 的志願序；同一號碼只能一門課。
        </p>
        {sync.error !== null && (
          <div className="alert alert-danger py-1.5 px-3 small rounded-3 mb-2" role="alert">
            {sync.error}
          </div>
        )}
        {activePlan === null ? (
          <p className="text-muted small mb-0 p-3 text-center bg-light rounded-3">
            先在左側建立或選擇一組課表。
          </p>
        ) : sync.orderedItems.length === 0 ? (
          <p className="text-muted small mb-0 p-3 text-center bg-light rounded-3">
            此課表尚無課程——到「查課·課表」加入後會自動寫入這一組。
          </p>
        ) : (
          <div className="priority-list-container">
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={onDragEnd}
            >
              <SortableContext
                items={sync.orderedItems.map((item) => item.courseId)}
                strategy={verticalListSortingStrategy}
              >
                <div role="list" aria-label="志願序列表">
                  {sync.orderedItems.map((item) => (
                    <SortablePriorityRow
                      key={item.courseId}
                      item={item}
                      onEditPriority={(raw) => {
                        sync.editPriority(item.courseId, raw);
                      }}
                      onRemove={() => remove(item.courseId)}
                    />
                  ))}
                </div>
              </SortableContext>
            </DndContext>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * 課表預覽・匯出 (todo 12): a read-only rendering of the ACTIVE plan's grid
 * (exactly the courses that carry time data - the same visual the ICS
 * document encodes) plus the two export affordances:
 *  - 下載 ICS: server-built RFC5545 file for the active plan (409 detail
 *    codes phrased via icsErrorMessage; empty plan -> friendly inline copy,
 *    never a corrupt download).
 *  - 下載 PNG: html-to-image capture of this preview grid at 2x; the
 *    empty-grid guard shows the friendly EmptyGridExportError copy instead
 *    of producing a blank file.
 */
function PlanExportCard({ sync }: { sync: PlansSyncContextValue }) {
  const gridRef = useRef<HTMLDivElement>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"ics" | "png" | null>(null);

  const activePlan =
    sync.plans.find((p) => p.id === sync.activePlanId) ?? null;
  const visualCourses: CourseOut[] = sync.orderedItems
    .map((item) => item.course)
    .filter(
      (course): course is CourseOut =>
        course !== null &&
        course.class_time !== null &&
        course.class_time.some((slot) => slot !== ""),
    );

  const onIcs = () => {
    if (activePlan === null || busy !== null) return;
    setBusy("ics");
    setExportError(null);
    downloadPlanIcs(activePlan.id)
      .catch((err: unknown) =>
        setExportError(
          err instanceof ApiError ? icsErrorMessage(err) : String(err),
        ),
      )
      .finally(() => setBusy(null));
  };

  const onPng = () => {
    const node = gridRef.current;
    if (activePlan === null || busy !== null) return;
    setExportError(null);
    if (node === null || visualCourses.length === 0) {
      setExportError("課表是空的——先去「查課·課表」加入有時段的課程，再下載 PNG。");
      return;
    }
    setBusy("png");
    downloadGridPng(node, activePlan.name, visualCourses.length)
      .catch((err: unknown) =>
        setExportError(err instanceof Error ? err.message : String(err)),
      )
      .finally(() => setBusy(null));
  };

  return (
    <div className="card shadow-sm border-0 rounded-4 mt-3">
      <div className="card-body p-3.5">
        <div className="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-2">
          <h2 className="h6 fw-bold mb-0">
            {activePlan !== null
              ? `「${activePlan.name}」課表預覽・匯出`
              : "課表預覽・匯出"}
          </h2>
          {activePlan !== null && (
            <div className="d-flex gap-2">
              <button
                type="button"
                className="btn btn-sm btn-outline-brand d-inline-flex align-items-center gap-1 shadow-sm"
                disabled={busy !== null}
                onClick={onIcs}
              >
                {busy === "ics" ? (
                  <ArrowRepeat className="spinner-border spinner-border-sm" aria-hidden />
                ) : (
                  <Calendar3 size={13} aria-hidden />
                )}
                <span>{busy === "ics" ? "匯出中…" : "下載 ICS"}</span>
              </button>
              <button
                type="button"
                className="btn btn-sm btn-brand d-inline-flex align-items-center gap-1 shadow-sm"
                disabled={busy !== null}
                onClick={onPng}
              >
                {busy === "png" ? (
                  <ArrowRepeat className="spinner-border spinner-border-sm" aria-hidden />
                ) : (
                  <Download size={13} aria-hidden />
                )}
                <span>{busy === "png" ? "匯出中…" : "下載課表 PNG"}</span>
              </button>
            </div>
          )}
        </div>
        {exportError !== null && (
          <div className="alert alert-warning py-1.5 px-3 small rounded-3 mt-2 mb-0" role="alert">
            {exportError}
          </div>
        )}
        {activePlan === null ? (
          <p className="text-muted small mt-2 mb-0 p-3 text-center bg-light rounded-3">
            先在左側建立或選擇一組課表。
          </p>
        ) : visualCourses.length === 0 ? (
          <p className="text-muted small mt-2 mb-0 p-3 text-center bg-light rounded-3">
            此課表沒有帶上課時段的課程——匯出的課表圖與 ICS 需要至少一門有時段的課。
          </p>
        ) : (
          <div ref={gridRef} className="mt-2" data-testid="plan-export-grid">
            <ScheduleTable
              selectedCourses={visualCourses}
              hoveredCourseId={null}
              onCourseHover={() => undefined}
              onCourseRemove={() => undefined}
              readOnly
            />
          </div>
        )}
      </div>
    </div>
  );
}

function PlansPage() {
  const sync = usePlansSync();
  return (
    <div className="row g-3">
      <div className="col-12 col-lg-4">
        <PlanListSidebar sync={sync} />
      </div>
      <div className="col-12 col-lg-8">
        <ActivePlanEditor sync={sync} />
        <PlanExportCard sync={sync} />
      </div>
    </div>
  );
}

export default PlansPage;
