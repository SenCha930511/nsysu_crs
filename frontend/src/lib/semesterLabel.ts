/** Display form of a year-semester code: "1151" -> "115-1". */
export function formatSemesterLabel(code: string): string {
  return code.length === 4 ? `${code.slice(0, 3)}-${code.slice(3)}` : code;
}
