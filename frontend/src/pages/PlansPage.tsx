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

import { useState } from "react";
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
import { GripVertical, Star, StarFill, Trash3 } from "react-bootstrap-icons";

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
        <GripVertical />
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
        <span className="fw-semibold">{name}</span>
        {!item.known && (
          <span className="badge text-bg-secondary ms-1">目錄查無此課</span>
        )}
        {meta !== "" && <div className="text-muted small">{meta}</div>}
      </div>
      <button
        type="button"
        className="btn btn-sm btn-outline-danger"
        aria-label={`從課表移除 ${name}`}
        onClick={onRemove}
      >
        <Trash3 />
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
    <div className="card">
      <div className="card-body">
        <h2 className="h6 fw-bold">我的課表</h2>
        <form className="input-group input-group-sm mb-2" onSubmit={onCreate}>
          <input
            type="text"
            className="form-control"
            placeholder="新課表名稱（如：志願A）"
            aria-label="新課表名稱"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <button type="submit" className="btn btn-primary" disabled={creating}>
            新增
          </button>
        </form>
        {actionError !== null && (
          <div className="alert alert-danger py-1 px-2 small" role="alert">
            {actionError}
          </div>
        )}
        {sync.plans.length === 0 && (
          <p className="text-muted small mb-0">
            尚無課表。建立第一組後，挑課會自動存入該組。
          </p>
        )}
        <div>
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
                  className="btn btn-sm p-0 border-0"
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
                    <StarFill className="text-warning" />
                  ) : (
                    <Star className="text-muted" />
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
                      active ? " fw-bold" : ""
                    }`}
                    onClick={() => void sync.selectPlan(plan.id)}
                  >
                    {plan.name}
                    <span className="text-muted small ms-1">
                      {plan.item_count} 門
                    </span>
                  </button>
                )}
                {plan.is_primary && (
                  <span className="badge text-bg-light border">主</span>
                )}
                <span className="ms-auto d-flex gap-1">
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-secondary"
                    onClick={() => {
                      setRenamingId(plan.id);
                      setRenameValue(plan.name);
                    }}
                  >
                    改名
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-danger"
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
                    刪除
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
    <div className="card">
      <div className="card-body">
        <div className="d-flex align-items-baseline justify-content-between">
          <h2 className="h6 fw-bold mb-1">
            {activePlan !== null ? `「${activePlan.name}」志願序` : "志願序"}
          </h2>
          {activePlan !== null && (
            <span className="text-muted small" role="status">
              {sync.saving ? "儲存中…" : "已自動儲存"}
            </span>
          )}
        </div>
        <p className="text-muted small mb-2">
          拖曳調整順序（自動編號 1…N），或直接輸入 1–20 的志願序；
          同一號碼只能一門課。志願序會用於初選志願排序。
        </p>
        {sync.error !== null && (
          <div className="alert alert-danger py-1 px-2 small" role="alert">
            {sync.error}
          </div>
        )}
        {activePlan === null ? (
          <p className="text-muted small mb-0">先在左側建立或選擇一組課表。</p>
        ) : sync.orderedItems.length === 0 ? (
          <p className="text-muted small mb-0">
            此課表尚無課程——到「查課·課表」加入後會自動寫入這一組。
          </p>
        ) : (
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
      </div>
    </div>
  );
}

export default PlansPage;
