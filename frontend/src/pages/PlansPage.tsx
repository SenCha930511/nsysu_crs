import { useCallback, useRef, useState } from "react";
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
  CardList,
  Copy,
  Download,
  Download as ImportIcon,
  GripVertical,
  Layers,
  Pencil,
  PlusLg,
  Search,
  Star,
  StarFill,
  Trash3,
  XLg,
} from "react-bootstrap-icons";

import type { CourseOut } from "../lib/api";
import { ApiError, fetchSelections } from "../lib/api";
import { downloadGridPng, downloadPlanIcs, icsErrorMessage } from "../lib/export";
import CourseBrowser from "../components/CourseBrowser";
import CourseDetailModal from "../components/CourseDetailModal";
import PlanCompare from "../components/PlanCompare";
import { useI18n } from "../lib/i18n";
import { buildSelectionGridCourses } from "../lib/selectionGrid";
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
  const { tx } = useI18n();
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
        aria-label={tx(`拖曳排序 ${name}`, `Drag to reorder ${name}`)}
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
        aria-label={tx(`志願序 ${name}`, `Priority of ${name}`)}
        onBlur={(e) => onEditPriority(e.currentTarget.value)}
        onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
          if (e.key === "Enter") e.currentTarget.blur();
        }}
      />
      <div className="priority-row-main">
        <span className="fw-bold text-dark">{name}</span>
        {!item.known && (
          <span className="badge text-bg-secondary ms-1">{tx("目錄查無此課", "Not in catalog")}</span>
        )}
        {meta !== "" && <div className="text-muted small mt-0.5">{meta}</div>}
      </div>
      <button
        type="button"
        className="btn btn-sm btn-outline-danger d-flex align-items-center justify-content-center p-1.5 rounded-2"
        aria-label={tx(`從課表移除 ${name}`, `Remove ${name} from the plan`)}
        onClick={onRemove}
      >
        <Trash3 size={13} />
      </button>
    </div>
  );
}

function PlanDeckOverview({ sync }: { sync: PlansSyncContextValue }) {
  const { tx } = useI18n();
  const [showCompare, setShowCompare] = useState(false);
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
            <div className="d-flex align-items-center gap-2">
              <h2 className="h5 fw-bold mb-1 text-dark d-flex align-items-center gap-2">
                <Layers className="text-teal-600" size={18} />
                <span>{tx("課表組合甲板 (Plan Deck)", "Plan Deck")}</span>
              </h2>
              <button
                type="button"
                className={`btn btn-sm rounded-pill px-3 d-inline-flex align-items-center gap-1 ${showCompare ? "btn-brand shadow-sm" : "btn-outline-secondary"}`}
                style={{ fontSize: "0.78rem" }}
                onClick={() => setShowCompare((v) => !v)}
                aria-pressed={showCompare}
              >
                <CardList size={12} />
                <span>{tx("方案對比", "Compare")}</span>
              </button>
            </div>
            <p className="text-muted small mb-0">
              {tx("建立多組不同選課方案（例如：衝堂備案、必修加選），自由切換測試。", "Create multiple course plans (e.g. clash backups, must-takes) and switch between them freely.")}
            </p>
          </div>

          <form className="d-flex align-items-center gap-2" onSubmit={onCreate}>
            <input
              type="text"
              className="form-control form-control-sm rounded-pill px-3"
              style={{ width: "200px" }}
              placeholder={tx("新增方案名稱…", "New plan name…")}
              aria-label={tx("新課表名稱", "New plan name")}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <button type="submit" className="btn btn-brand btn-sm rounded-pill px-3 d-inline-flex align-items-center gap-1 shadow-sm" disabled={creating}>
              <PlusLg size={13} />
              <span>{tx("建立方案", "Create plan")}</span>
            </button>
          </form>
        </div>

        {actionError !== null && (
          <div className="alert alert-danger py-1.5 px-3 small rounded-3 mb-3" role="alert">
            {actionError}
          </div>
        )}

        {showCompare && sync.plans.length >= 2 && (
          <PlanCompare plans={sync.plans} defaultA={sync.activePlanId} />
        )}
        {showCompare && sync.plans.length < 2 && (
          <div className="text-center p-3 mb-3 bg-light rounded-4 text-muted small">
            {tx("對比需要至少兩組方案；先用「複製」快速生一組副本試試。", "Comparison needs at least two plans — try duplicating one with the copy button to get going.")}
          </div>
        )}

        {sync.plans.length === 0 ? (
          <div className="text-center p-4 bg-light rounded-4 text-muted small">
            {tx("尚無任何課表方案。輸入名稱並點擊「建立方案」即可開始！", "No plans yet. Enter a name and hit “Create plan” to start!")}
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
                          plan.is_primary
                            ? tx(`主課表 ${plan.name}`, `Primary plan ${plan.name}`)
                            : tx(`設為主課表 ${plan.name}`, `Set ${plan.name} as primary`)
                        }
                        title={plan.is_primary ? tx("主課表", "Primary plan") : tx("設為主課表", "Set as primary")}
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
                          aria-label={tx(`改名 ${plan.name}`, `Rename ${plan.name}`)}
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
                          {tx("主課表", "Primary")}
                        </span>
                      )}
                      {active && (
                        <span className="badge bg-teal-100 text-teal-800 border border-teal-300">
                          {tx("使用中", "Active")}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="d-flex align-items-center justify-content-between pt-2 border-top mt-2">
                    <span className="text-muted font-monospace" style={{ fontSize: "0.78rem" }}>
                      {tx(`${plan.item_count} 門課程`, `${plan.item_count} courses`)}
                    </span>

                    <div className="d-flex align-items-center gap-1">
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-secondary p-1 rounded-2"
                        title={tx(`改名 ${plan.name}`, `Rename ${plan.name}`)}
                        aria-label={tx(`改名 ${plan.name}`, `Rename ${plan.name}`)}
                        onClick={(e) => {
                          e.stopPropagation();
                          setRenamingId(plan.id);
                          setRenameValue(plan.name);
                        }}
                      >
                        <Pencil size={12} />
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-secondary p-1 rounded-2"
                        title={tx(`複製 ${plan.name}`, `Duplicate ${plan.name}`)}
                        aria-label={tx(`複製 ${plan.name}`, `Duplicate ${plan.name}`)}
                        onClick={(e) => {
                          e.stopPropagation();
                          sync.clone(plan.id).catch((err: unknown) => {
                            setActionError(
                              err instanceof Error ? err.message : String(err),
                            );
                          });
                        }}
                      >
                        <Copy size={12} />
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-secondary p-1 rounded-2"
                        title={tx(`匯出 ${plan.name} 的 ICS 行事曆`, `Export ${plan.name} as ICS`)}
                        aria-label={tx(`匯出 ${plan.name} 的 ICS 行事曆`, `Export ${plan.name} as ICS`)}
                        disabled={icsBusyId === plan.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          onIcs(plan.id);
                        }}
                      >
                        <Download size={12} />
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-danger p-1 rounded-2"
                        title={tx(`刪除 ${plan.name}`, `Delete ${plan.name}`)}
                        aria-label={tx(`刪除 ${plan.name}`, `Delete ${plan.name}`)}
                        disabled={sync.plans.length <= 1}
                        onClick={(e) => {
                          e.stopPropagation();
                          if (
                            window.confirm(
                              tx(
                                `確定要刪除「${plan.name}」嗎？`,
                                `Delete plan "${plan.name}"?`,
                              ),
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

function ActivePlanEditor({
  sync,
  onOpenSearch,
}: {
  sync: PlansSyncContextValue;
  onOpenSearch: () => void;
}) {
  const { tx } = useI18n();
  const { selected, add, remove } = useSelection();
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState<string | null>(null);

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

  const onImportEnrolled = useCallback(() => {
    if (importing) return;
    setImporting(true);
    setImportMsg(null);
    fetchSelections()
      .then((body) => {
        const { courses } = buildSelectionGridCourses(body.items);
        const existingIds = new Set(selected.map((c) => c.id));
        let addedCount = 0;
        for (const course of courses) {
          if (!existingIds.has(course.id)) {
            add(course);
            addedCount++;
          }
        }
        setImportMsg(
          addedCount > 0
            ? tx(`成功匯入 ${addedCount} 門已選課程至本方案！`, `Imported ${addedCount} enrolled course(s) into this plan!`)
            : tx("目前已選課程皆已存在於此方案中。", "All enrolled courses are already in this plan."),
        );
      })
      .catch((err: unknown) => {
        setImportMsg(
          err instanceof Error ? err.message : tx("匯入失敗，請稍候重試", "Import failed. Please try again."),
        );
      })
      .finally(() => setImporting(false));
  }, [importing, selected, add, tx]);

  const activePlan = sync.plans.find((p) => p.id === sync.activePlanId) ?? null;

  return (
    <div className="card shadow-sm border-0 rounded-4 mb-4">
      <div className="card-body p-4">
        <div className="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-2">
          <div>
            <h2 className="h6 fw-bold mb-0 text-dark">
              {activePlan !== null
                ? tx(`「${activePlan.name}」志願序排序台`, `"${activePlan.name}" priority board`)
                : tx("志願序排序", "Priority order")}
            </h2>
            <p className="text-muted small mb-0 mt-0.5">
              {tx("拖曳左側手柄調整順序（自動編號 1…N），或手動輸入 1–20 的志願序。", "Drag handle to reorder (1…N), or type 1–20 directly in the box.")}
            </p>
          </div>

          {activePlan !== null && (
            <div className="d-flex align-items-center gap-2">
              <button
                type="button"
                className="btn btn-sm btn-outline-brand rounded-pill px-3 d-inline-flex align-items-center gap-1.5 fw-semibold shadow-xs"
                onClick={onImportEnrolled}
                disabled={importing}
              >
                <ImportIcon size={12} />
                <span>{importing ? tx("匯入中…", "Importing…") : tx("匯入已選課程", "Import enrolled")}</span>
              </button>

              <button
                type="button"
                className="btn btn-sm btn-brand rounded-pill px-3 d-inline-flex align-items-center gap-1.5 fw-semibold shadow-sm"
                onClick={onOpenSearch}
              >
                <PlusLg size={12} />
                <span>{tx("搜尋加入課程", "Add courses")}</span>
              </button>
            </div>
          )}
        </div>

        {importMsg !== null && (
          <div className="alert alert-info py-1.5 px-3 small rounded-3 mb-2" role="status">
            {importMsg}
          </div>
        )}

        {sync.error !== null && (
          <div className="alert alert-danger py-1.5 px-3 small rounded-3 mb-2" role="alert">
            {sync.error}
          </div>
        )}

        {activePlan === null ? (
          <div className="text-center p-4 bg-light rounded-4 text-muted small">
            {tx("請先在上方甲板選擇或建立一組課表方案。", "Pick or create a plan in the deck above first.")}
          </div>
        ) : sync.orderedItems.length === 0 ? (
          <div className="text-center p-4 bg-light rounded-4 text-muted small">
            <p className="mb-2">{tx("此方案尚無課程——您可以點擊上方「搜尋加入課程」或「匯入已選課程」。", "This plan has no courses — click “Add courses” or “Import enrolled” above to get started.")}</p>
            <button
              type="button"
              className="btn btn-sm btn-brand rounded-pill px-3.5 py-1.5 fw-semibold d-inline-flex align-items-center gap-1.5 shadow-sm"
              onClick={onOpenSearch}
            >
              <Search size={13} />
              <span>{tx("立即搜尋並加入課程", "Search & add courses now")}</span>
            </button>
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
                <div role="list" aria-label={tx("志願序列表", "Priority list")}>
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
  const { tx } = useI18n();
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
      setExportError(tx("課表是空的——先加入有時段的課程，再下載 PNG。", "The timetable is empty — add time-slotted courses before downloading a PNG."));
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
                ? tx(`「${activePlan.name}」方案課表畫布與匯出`, `"${activePlan.name}" timetable canvas & export`)
                : tx("方案課表預覽・匯出", "Plan timetable preview & export")}
            </h2>
            <p className="text-muted small mb-0 mt-0.5">
              {tx("輸出為高解析度圖片或加入 Google / Apple Calendar 行事曆。", "Export as a high-resolution image, or push into Google / Apple Calendar.")}
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
                <span>{busy === "ics" ? tx("匯出中…", "Exporting…") : tx("匯出 ICS 行事曆", "Export ICS calendar")}</span>
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
                <span>{busy === "png" ? tx("匯出中…", "Exporting…") : tx("下載課表 PNG", "Download PNG")}</span>
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
            {tx("請先在上方甲板選擇或建立一組課表方案。", "Pick or create a plan in the deck above first.")}
          </p>
        ) : visualCourses.length === 0 ? (
          <p className="text-muted small mb-0 p-4 text-center bg-light rounded-4">
            {tx("此方案尚未包含具時段之課程——匯出需至少包含一門有時段的課。", "This plan has no time-slotted courses yet — exporting needs at least one.")}
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
  const { tx } = useI18n();
  const sync = usePlansSync();
  const { isSelected, toggle } = useSelection();
  const [showSearchModal, setShowSearchModal] = useState(false);
  const [detailCourse, setDetailCourse] = useState<CourseOut | null>(null);

  const activePlan = sync.plans.find((p) => p.id === sync.activePlanId) ?? null;

  return (
    <div className="pb-4">
      {/* Top Deck: Plan Deck Overview */}
      <PlanDeckOverview sync={sync} />

      {/* Bottom Area: Priority Editor & Export Canvas */}
      <div className="row g-4">
        <div className="col-12 col-xl-5">
          <ActivePlanEditor sync={sync} onOpenSearch={() => setShowSearchModal(true)} />
        </div>
        <div className="col-12 col-xl-7">
          <PlanExportCard sync={sync} />
        </div>
      </div>

      {/* Course Search Modal for Plan Lab */}
      {showSearchModal && (
        <div
          className="modal fade show d-block"
          tabIndex={-1}
          role="dialog"
          style={{ backgroundColor: "rgba(15, 23, 42, 0.65)", backdropFilter: "blur(4px)", zIndex: 1060 }}
          onClick={() => setShowSearchModal(false)}
        >
          <div
            className="modal-dialog modal-xl modal-dialog-centered modal-dialog-scrollable"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: "880px" }}
          >
            <div className="modal-content border-0 shadow-lg rounded-4 overflow-hidden" style={{ maxHeight: "88vh" }}>
              <div className="modal-header border-bottom py-3 px-4 bg-white d-flex align-items-center justify-content-between">
                <div className="d-flex align-items-center gap-2.5">
                  <div className="p-2 rounded-3 bg-teal-50 text-teal-700 d-inline-flex align-items-center justify-content-center">
                    <Search size={18} />
                  </div>
                  <div>
                    <h5 className="modal-title fw-bold text-dark mb-0">
                      {activePlan !== null
                        ? tx(`搜尋並加入課程至「${activePlan.name}」`, `Search & add courses to "${activePlan.name}"`)
                        : tx("搜尋並加入課程", "Search and add courses")}
                    </h5>
                    <p className="text-muted small mb-0" style={{ fontSize: "0.82rem" }}>
                      {tx("點擊「加入課表」即可立即加入至此方案中。", "Click “Add” on any course to put it into this plan immediately.")}
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  className="btn-close"
                  aria-label={tx("關閉", "Close")}
                  onClick={() => setShowSearchModal(false)}
                />
              </div>

              <div className="modal-body p-0 overflow-y-auto" style={{ height: "620px" }}>
                <CourseBrowser
                  hoveredCourseId={null}
                  onCourseHover={() => undefined}
                  pickState={(course) => (isSelected(course.id) ? "selected" : null)}
                  onToggleCourse={(course) => toggle(course)}
                  onViewCourse={setDetailCourse}
                />
              </div>

              <div className="modal-footer border-top py-2.5 px-4 bg-light d-flex justify-content-between">
                <span className="text-muted small">
                  {tx(
                    `目前方案共 ${sync.orderedItems.length} 門課程`,
                    `Current plan: ${sync.orderedItems.length} courses`,
                  )}
                </span>
                <button
                  type="button"
                  className="btn btn-brand rounded-pill px-4 py-1.5 fw-semibold shadow-xs"
                  onClick={() => setShowSearchModal(false)}
                >
                  {tx("完成", "Done")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Course Detail Modal */}
      {detailCourse !== null && (
        <CourseDetailModal course={detailCourse} onClose={() => setDetailCourse(null)} />
      )}
    </div>
  );
}

export default PlansPage;
