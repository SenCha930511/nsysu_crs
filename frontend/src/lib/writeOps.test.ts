import { describe, expect, it } from "vitest";

import type { CourseOut, JobOpOut, SelectionItem } from "./api";
import {
  SUPERSEDED_COPY,
  buildPreviewOps,
  buildReconcileRows,
  blockedCount,
  canConfirm,
  checkConfirmForm,
  composerReducer,
  confirmFormErrorText,
  dropIncludable,
  initComposer,
  isTerminalStatus,
  jobStatusCopy,
  outcomeCopy,
  priorityErrorText,
  unknownReconciledHint,
  unprioritizedAdds,
  verdictLabel,
  verdictTone,
} from "./writeOps";
import type { ComposerState } from "./writeOps";

function course(partial: Partial<CourseOut>): CourseOut {
  return {
    id: "uuid-1",
    year_sem: "1151",
    code: null,
    dept: null,
    grade: null,
    class_: null,
    name_zh: "線性代數",
    name_en: null,
    credit: 3,
    compulsory: false,
    restrict: 60,
    select_n: 50,
    selected_n: 40,
    remaining: 10,
    teacher: "王老師",
    room: "理SC 2001",
    class_time: ["", "", "56", "", "", "", ""],
    description: null,
    tags: null,
    english: false,
    change: null,
    change_desc: null,
    url: null,
    ingested_at: "2026-08-28T03:10:00+08:00",
    ...partial,
  };
}

function selection(partial: Partial<SelectionItem>): SelectionItem {
  return {
    code: "M3046243",
    course_no: "CSE515",
    state: "選上",
    dept: "資工系",
    name: "計算機結構",
    credit: 3,
    compulsory_elective: "必修",
    teacher: "陳老師",
    room_text: "三2,3,4 工EC 5012",
    points_priority: null,
    stage: "加退選",
    year_semest_note: "",
    times: "三2,3,4",
    room: "工EC 5012",
    unknown: false,
    course_id: "uuid-drop-1",
    ...partial,
  };
}

const PLAN_ITEMS = [
  { courseId: "uuid-1", priority: 1, course: course({ id: "uuid-1", code: "GEAE2526" }) },
  { courseId: "uuid-2", priority: 2, course: course({ id: "uuid-2", code: "MEME101B", name_zh: "微積分" }) },
];

const SELECTION_ITEMS = [
  selection({}),
  selection({ code: "PHYSCI10", name: "普通物理", state: "登記加選", course_id: null }),
  selection({ code: "FAILEDX9", name: "失敗課", state: "失敗", course_id: null }),
  selection({ code: null, name: "無碼課", state: "選上", course_id: null }),
];

function freshComposer(): ComposerState {
  return initComposer(PLAN_ITEMS, SELECTION_ITEMS);
}

describe("initComposer", () => {
  it("builds add drafts from plan items with existing priorities", () => {
    const state = freshComposer();
    expect(state.adds.map((a) => [a.courseId, a.priority])).toEqual([
      ["uuid-1", 1],
      ["uuid-2", 2],
    ]);
  });

  it("keeps only held selections with a code as drop candidates", () => {
    const state = freshComposer();
    expect(state.drops.map((d) => d.key)).toEqual(["M3046243", "PHYSCI10"]);
  });
});

describe("composer reducer: priority edits", () => {
  it("sets a free priority", () => {
    const state = composerReducer(freshComposer(), {
      type: "setPriority",
      courseId: "uuid-2",
      raw: "5",
    });
    expect(state.adds.find((a) => a.courseId === "uuid-2")?.priority).toBe(5);
    expect(state.priorityError).toBeNull();
  });

  it.each(["0", "21", "99"])("rejects out-of-range %s", (raw) => {
    const before = freshComposer();
    const state = composerReducer(before, {
      type: "setPriority",
      courseId: "uuid-1",
      raw,
    });
    expect(state.priorityError).toBe("priority_range");
    expect(state.adds).toBe(before.adds);
  });

  it("rejects non-numeric input", () => {
    const state = composerReducer(freshComposer(), {
      type: "setPriority",
      courseId: "uuid-1",
      raw: "x1",
    });
    expect(state.priorityError).toBe("priority_invalid");
  });

  it("rejects a duplicate priority and names the holder", () => {
    const before = freshComposer();
    const state = composerReducer(before, {
      type: "setPriority",
      courseId: "uuid-2",
      raw: "1",
    });
    expect(state.priorityError).toBe("priority_duplicate");
    expect(state.priorityErrorHolder).toBe("uuid-1");
    expect(state.adds.find((a) => a.courseId === "uuid-2")?.priority).toBe(2);
    expect(priorityErrorText("priority_duplicate")).toBe("志願序不可重複");
    expect(priorityErrorText("priority_range")).toBe("志願序須為 1–20 的整數");
  });

  it("clears to unprioritized and excludes the row from preview ops", () => {
    const state = composerReducer(freshComposer(), {
      type: "setPriority",
      courseId: "uuid-1",
      raw: "",
    });
    expect(state.adds.find((a) => a.courseId === "uuid-1")?.priority).toBeNull();
    expect(unprioritizedAdds(state).map((a) => a.courseId)).toEqual(["uuid-1"]);
    expect(
      buildPreviewOps(state).filter((op) => op.course_id === "uuid-1"),
    ).toEqual([]);
  });
});

describe("composer reducer: drop typed-code gating", () => {
  it("is not includable while typed is empty or mismatched", () => {
    expect(dropIncludable({ typed: "", code: "M3046243" })).toBe(false);
    expect(dropIncludable({ typed: "M304624X", code: "M3046243" })).toBe(false);
    expect(dropIncludable({ typed: "m3046243", code: "M3046243" })).toBe(false);
  });

  it("becomes includable on the exact 8-char code and enters preview ops", () => {
    const matched = composerReducer(freshComposer(), {
      type: "setDropTyped",
      key: "PHYSCI10",
      typed: "PHYSCI10",
    });
    const drop = matched.drops.find((d) => d.key === "PHYSCI10");
    expect(drop !== undefined && dropIncludable(drop)).toBe(true);
    const ops = buildPreviewOps(matched);
    expect(ops).toContainEqual({
      action: "-",
      course_id: "PHYSCI10", // code fallback when catalog join is null
      drop_confirm_text: "PHYSCI10",
    });
    // "-" ops must never carry a priority
    for (const op of ops) {
      if (op.action === "-") expect(op.priority).toBeUndefined();
    }
    const brokenAgain = composerReducer(matched, {
      type: "setDropTyped",
      key: "PHYSCI10",
      typed: "PHYSCI1",
    });
    expect(
      buildPreviewOps(brokenAgain).some((op) => op.course_id === "PHYSCI10"),
    ).toBe(false);
  });

  it("uses the catalog UUID for drop course_id when the join exists", () => {
    const state = composerReducer(freshComposer(), {
      type: "setDropTyped",
      key: "M3046243",
      typed: "M3046243",
    });
    expect(buildPreviewOps(state)).toContainEqual({
      action: "-",
      course_id: "uuid-drop-1",
      drop_confirm_text: "M3046243",
    });
  });

  it("reinit preserves already-typed codes for rows still present", () => {
    const typedState = composerReducer(freshComposer(), {
      type: "setDropTyped",
      key: "M3046243",
      typed: "M3046243",
    });
    const next = composerReducer(typedState, {
      type: "reinit",
      planItems: PLAN_ITEMS,
      selectionItems: SELECTION_ITEMS,
    });
    expect(next.drops.find((d) => d.key === "M3046243")?.typed).toBe("M3046243");
  });

  it("removeAdd / removeDrop drop rows from the batch", () => {
    let state = composerReducer(freshComposer(), {
      type: "removeAdd",
      courseId: "uuid-1",
    });
    state = composerReducer(state, { type: "removeDrop", key: "PHYSCI10" });
    expect(state.adds.map((a) => a.courseId)).toEqual(["uuid-2"]);
    expect(state.drops.map((d) => d.key)).toEqual(["M3046243"]);
  });
});

describe("verdict-block logic", () => {
  const okOp = { writable: true, verdict: "ok", detail: null, warnings: [] };
  const blockedOp = {
    writable: false,
    verdict: "衝堂",
    detail: "M3046243",
    warnings: [],
  };
  const warnOp = { ...okOp, warnings: ["remaining_zero"] };

  it("blocked > 0 disables confirm even when the batch flag says writable", () => {
    expect(
      canConfirm({ writable: true, confirm_token: "t", ops: [okOp, blockedOp] }),
    ).toBe(false);
    expect(blockedCount({ ops: [okOp, blockedOp, blockedOp] })).toBe(2);
  });

  it("confirm requires a minted token and zero blocked rows", () => {
    expect(canConfirm(null)).toBe(false);
    expect(canConfirm({ writable: false, confirm_token: null, ops: [blockedOp] })).toBe(
      false,
    );
    expect(canConfirm({ writable: true, confirm_token: null, ops: [okOp] })).toBe(
      false,
    );
    expect(
      canConfirm({ writable: true, confirm_token: "tok", ops: [okOp, warnOp] }),
    ).toBe(true); // warnings never block
  });

  it("tones and labels: blocked red, warn yellow, pass green", () => {
    expect(verdictTone(blockedOp)).toBe("blocked");
    expect(verdictTone(warnOp)).toBe("warn");
    expect(verdictTone(okOp)).toBe("pass");
    expect(verdictLabel(blockedOp)).toBe("衝堂（與 M3046243）");
    expect(verdictLabel({ ...okOp })).toBe("通過");
    expect(verdictLabel({ ...blockedOp, verdict: "無課號", detail: null })).toBe(
      "無課號",
    );
  });
});

describe("confirm modal asserts", () => {
  const matched = [{ key: "M3046243", code: "M3046243", typed: "M3046243" }];
  const mismatched = [{ key: "M3046243", code: "M3046243", typed: "" }];

  it("password is required", () => {
    const check = checkConfirmForm("", matched);
    expect(check.ok).toBe(false);
    expect(check.error).toBe("password_required");
    expect(confirmFormErrorText("password_required")).toContain("重新輸入選課密碼");
  });

  it("every drop code must match (carried from composer, re-asserted)", () => {
    const check = checkConfirmForm("secret1", mismatched);
    expect(check.ok).toBe(false);
    expect(check.error).toBe("drop_code_mismatch");
    expect(check.mismatchKey).toBe("M3046243");
    expect(checkConfirmForm("secret1", matched).ok).toBe(true);
    expect(checkConfirmForm("secret1", []).ok).toBe(true);
  });
});

describe("outcome/status copy tables", () => {
  const OUTCOMES = [
    "success",
    "failed",
    "transport_failed",
    "parse_failed",
    "階段逾時",
    "unknown-reconciled",
    "session_superseded",
    "pending",
  ];

  it("every outcome has a copy row", () => {
    for (const outcome of OUTCOMES) {
      const copy = outcomeCopy(outcome);
      expect(copy.label.length).toBeGreaterThan(0);
      expect(copy.tone.length).toBeGreaterThan(0);
    }
  });

  it("business failures never suggest auto-retry", () => {
    const copy = outcomeCopy("failed");
    const text = `${copy.label}${copy.hint ?? ""}`;
    expect(text).not.toMatch(/重試|重送|再次送出|重新嘗試|retry/i);
  });

  it("session_superseded copy is the fixed dedicated text everywhere", () => {
    expect(SUPERSEDED_COPY).toBe(
      "你已在別處重新登入，此批送單已取消，請重新預檢",
    );
    expect(outcomeCopy("session_superseded").hint).toBe(SUPERSEDED_COPY);
  });

  it("unknown-reconciled has two fixed variants keyed by the reconcile flag", () => {
    expect(unknownReconciledHint(null)).toBe("學校回應不明—已自動對帳");
    expect(unknownReconciledHint("manual_resync_needed")).toBe(
      "學校回應不明——請手動重新同步對帳",
    );
  });

  it("階段逾時 copy carries the re-preview CTA", () => {
    expect(outcomeCopy("階段逾時").hint).toContain("重新預檢");
  });

  it("null outcome renders as pending", () => {
    expect(outcomeCopy(null).label).toBe("等待回應");
  });

  it("job statuses: all six covered, terminal set is exact", () => {
    const statuses = [
      "queued",
      "running",
      "done",
      "failed",
      "cancelled",
      "session_superseded",
    ];
    for (const status of statuses) {
      expect(jobStatusCopy(status).label.length).toBeGreaterThan(0);
    }
    expect(isTerminalStatus("queued")).toBe(false);
    expect(isTerminalStatus("running")).toBe(false);
    expect(isTerminalStatus("done")).toBe(true);
    expect(isTerminalStatus("failed")).toBe(true);
    expect(isTerminalStatus("cancelled")).toBe(true);
    expect(isTerminalStatus("session_superseded")).toBe(true);
  });
});

describe("reconcile diff", () => {
  const ops: Pick<JobOpOut, "code" | "action" | "priority">[] = [
    { code: "GEAE2526", action: "+", priority: 1 },
    { code: "M3046243", action: "-", priority: null },
  ];

  it("matches intent against the latest school truth per code", () => {
    const rows = buildReconcileRows(ops, [
      selection({ code: "GEAE2526", state: "選上" }),
    ]);
    expect(rows).toEqual([
      {
        code: "GEAE2526",
        intent: "+",
        intentLabel: "加選（志願 1）",
        actualState: "選上",
        actualName: "計算機結構",
        match: true,
      },
      {
        code: "M3046243",
        intent: "-",
        intentLabel: "退選",
        actualState: null,
        actualName: null,
        match: true,
      },
    ]);
  });

  it("flags mismatches: add not held, drop still held", () => {
    const rows = buildReconcileRows(ops, [
      selection({ code: "M3046243", state: "選上" }),
    ]);
    expect(rows.find((r) => r.code === "GEAE2526")?.match).toBe(false);
    expect(rows.find((r) => r.code === "M3046243")?.match).toBe(false);
  });
});
