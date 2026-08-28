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
  Download,
  GripVertical,
  Layers,
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
        <span className="fw-bold text-dark">{name}</span>
        {!item.known && (
          <span className="badge text-bg-secondary ms-1">目錄查無此課</span>
        )}
        {meta !== "" && <div className="text-muted small mt-0.5">{meta}</div>}
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

function PlanDeckOverview({ sync }: { sync: PlansSyncContextValue }) {
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
    <div className="card shadow-sm border-0 rounded-4 mb-4">
      <div className="card-body p-4">
        <div className="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-3">
          <div>
            <h2 className="h5 fw-bold mb-1 text-dark d-flex align-items-center gap-2">
              <Layers className="text-teal-600" size={18} />
              <span>課表組合甲板 (Plan Deck)</span>
            </h2>
            <p className="text-muted small mb-0">
              建立多組不同選課方案（例如：衝堂備案、必修加選），自由切換測試。
            </p>
          </div>

          <form className="d-flex align-items-center gap-2" onSubmit={onCreate}>
            <input
              type="text"
              className="form-control form-control-sm rounded-pill px-3"
              style={{ width: "200px" }}
              placeholder="新增方案名稱…"
              aria-label="新課表名稱"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <button type="submit" className="btn btn-brand btn-sm rounded-pill px-3 d-inline-flex align-items-center gap-1 shadow-sm" disabled={creating}>
              <PlusLg size={13} />
              <span>建立方案</span>
            </button>
          </form>
        </div>

        {actionError !== null && (
          <div className="alert alert-danger py-1.5 px-3 small rounded-3 mb-3" role="alert">
            {actionError}
          </div>
        )}

        {sync.plans.length === 0 ? (
          <div className="text-center p-4 bg-light rounded-4 text-muted small">
            尚無任何課表方案。輸入名稱並點擊「建立方案」即可開始！
          </div>
        ) : (
          <div className="plan-deck-container">
            {sync.plans.map((plan) => {
              const active = plan.id === sync.activePlanId;
              return (
                <div
                  key={plan.id}
                  className={`plan-deck-card plan-row ${active ? "is-active-plan plan-row-active" : ""}`}
                  data-plan-id={plan.id}
                  onClick={() => void sync.selectPlan(plan.id)}
                >
                  <div className="d-flex align-items-center justify-content-between mb-2">
                    <div className="d-flex align-items-center gap-2">
                      <button
                        type="button"
                        className="btn btn-sm p-0 border-0 bg-transparent"
                        aria-label={
                          plan.is_primary ? `主課表 ${plan.name}` : `設為主課表 ${plan.name}`
                        }
                        title={plan.is_primary ? "主課表" : "設為主課表"}
                        onClick={(e) => {
                          e.stopPropagation();
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
                          <StarFill className="text-warning" size={17} />
                        ) : (
                          <Star className="text-muted" size={17} />
                        )}
                      </button>

                      {renamingId === plan.id ? (
                        <input
                          type="text"
                          className="form-control form-control-sm"
                          defaultValue={plan.name}
                          aria-label={`改名 ${plan.name}`}
                          autoFocus
                          onClick={(e) => e.stopPropagation()}
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
                          className={`btn btn-sm plan-switch p-0 text-dark fw-bold text-start`}
                          style={{ fontSize: "0.95rem" }}
                          onClick={() => void sync.selectPlan(plan.id)}
                        >
                          {plan.name}
                        </button>
                      )}
                    </div>

                    <div className="d-flex align-items-center gap-1">
                      {plan.is_primary && (
                        <span className="badge bg-amber-100 text-amber-800 border border-amber-300">
                          主課表
                        </span>
                      )}
                      {active && (
                        <span className="badge bg-teal-100 text-teal-800 border border-teal-300">
                          使用中
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="d-flex align-items-center justify-content-between pt-2 border-top mt-2">
                    <span className="badge text-bg-light border text-muted">
                      共 {plan.item_count} 門課程
                    </span>

                    <div className="d-flex align-items-center gap-1" onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-secondary p-1 px-2 rounded-2"
                        title="下載 ICS 行事曆"
                        disabled={icsBusyId !== null}
                        onClick={() => onIcs(plan.id)}
                      >
                        <Calendar3 size={12} className="me-1" />
                        <span style={{ fontSize: "0.74rem" }}>{icsBusyId === plan.id ? "…" : "ICS"}</span>
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-secondary p-1 px-2 rounded-2"
                        title="重新命名"
                        onClick={() => {
                          setRenamingId(plan.id);
                          setRenameValue(plan.name);
                        }}
                      >
                        <Pencil size={12} />
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-danger p-1 px-2 rounded-2"
                        title="刪除方案"
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
                        <Trash3 size={12} />
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
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
    <div className="card shadow-sm border-0 rounded-4 mb-4">
      <div className="card-body p-4">
        <div className="d-flex align-items-center justify-content-between mb-2">
          <h2 className="h6 fw-bold mb-0 text-dark">
            {activePlan !== null ? `「${activePlan.name}」志願序排序台` : "志願序排序"}
          </h2>
          {activePlan !== null && (
            <span className="badge text-bg-light border text-muted" role="status">
              {sync.saving ? "儲存中…" : "已即時同步"}
            </span>
          )}
        </div>
        <p className="text-muted small mb-3">
          拖曳左側手柄調整順序（自動編號 1…N），或在格子內手動輸入 1–20 的志願序。
        </p>

        {sync.error !== null && (
          <div className="alert alert-danger py-1.5 px-3 small rounded-3 mb-2" role="alert">
            {sync.error}
          </div>
        )}

        {activePlan === null ? (
          <div className="text-center p-4 bg-light rounded-4 text-muted small">
            請先在上方甲板選擇或建立一組課表方案。
          </div>
        ) : sync.orderedItems.length === 0 ? (
          <div className="text-center p-4 bg-light rounded-4 text-muted small">
            此方案尚無課程——到「查課・課表」加入課程後會自動寫入此方案。
          </div>
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
    <div className="card shadow-sm border-0 rounded-4">
      <div className="card-body p-4">
        <div className="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-3">
          <div>
            <h2 className="h6 fw-bold mb-0 text-dark">
              {activePlan !== null
                ? `「${activePlan.name}」方案課表畫布與匯出`
                : "方案課表預覽・匯出"}
            </h2>
            <p className="text-muted small mb-0 mt-0.5">
              輸出為高解析度圖片或加入 Google / Apple Calendar 行事曆。
            </p>
          </div>
          {activePlan !== null && (
            <div className="d-flex gap-2">
              <button
                type="button"
                className="btn btn-sm btn-outline-brand rounded-pill px-3 d-inline-flex align-items-center gap-1 shadow-sm"
                disabled={busy !== null}
                onClick={onIcs}
              >
                {busy === "ics" ? (
                  <ArrowRepeat className="spinner-border spinner-border-sm" aria-hidden />
                ) : (
                  <Calendar3 size={13} aria-hidden />
                )}
                <span>{busy === "ics" ? "匯出中…" : "匯出 ICS 行事曆"}</span>
              </button>
              <button
                type="button"
                className="btn btn-sm btn-brand rounded-pill px-3 d-inline-flex align-items-center gap-1 shadow-sm"
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
          <div className="alert alert-warning py-1.5 px-3 small rounded-3 mb-2" role="alert">
            {exportError}
          </div>
        )}

        {activePlan === null ? (
          <p className="text-muted small mb-0 p-4 text-center bg-light rounded-4">
            請先在上方甲板選擇或建立一組課表方案。
          </p>
        ) : visualCourses.length === 0 ? (
          <p className="text-muted small mb-0 p-4 text-center bg-light rounded-4">
            此方案尚未包含具時段之課程——匯出需至少包含一門有時段的課。
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
    <div className="pb-4">
      {/* Top Deck: Plan Deck Overview */}
      <PlanDeckOverview sync={sync} />

      {/* Bottom Area: Priority Editor & Export Canvas */}
      <div className="row g-4">
        <div className="col-12 col-xl-5">
          <ActivePlanEditor sync={sync} />
        </div>
        <div className="col-12 col-xl-7">
          <PlanExportCard sync={sync} />
        </div>
      </div>
    </div>
  );
}

export default PlansPage;
