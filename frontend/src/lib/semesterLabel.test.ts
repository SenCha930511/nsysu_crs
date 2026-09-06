import { describe, expect, it } from "vitest";

import { formatSemesterLabel } from "./semesterLabel";

describe("formatSemesterLabel", () => {
  it("inserts a dash between the ROC year and the semester digit", () => {
    // Given a standard 4-char code
    // When formatted
    // Then a dash separates year and semester
    expect(formatSemesterLabel("1151")).toBe("115-1");
    expect(formatSemesterLabel("1152")).toBe("115-2");
  });

  it("passes non-standard shapes through untouched", () => {
    expect(formatSemesterLabel("115")).toBe("115");
    expect(formatSemesterLabel("")).toBe("");
  });
});
