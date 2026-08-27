/**
 * Credit & hours totals over the current selection.
 *
 * Adapted from NSYSU-OpenDev/NSYSUSelectorHelper (MIT License,
 * Copyright (c) Cellery Lin and whats2000):
 *   client-website/src/components/SelectorSetting.tsx
 *   (calculateTotalCreditsAndHours)
 *   https://github.com/NSYSU-OpenDev/NSYSUSelectorHelper
 *
 * Hours = number of occupied period codes across the week (one period = one
 * hour block on the grid). Day strings are validated (unknown codes throw)
 * so corrupt data cannot silently under-count.
 */

import { parseDayTimeString } from "../config/timeslots";
import type { CourseOut } from "./api";

export interface Totals {
  totalCredits: number;
  totalHours: number;
  courseCount: number;
}

export function totalCreditsAndHours(
  courses: readonly CourseOut[],
): Totals {
  let totalCredits = 0;
  let totalHours = 0;
  for (const course of courses) {
    totalCredits += course.credit ?? 0;
    for (let day = 0; day < 7; day++) {
      const raw = (course.class_time ?? [])[day] ?? "";
      totalHours += parseDayTimeString(raw).size;
    }
  }
  return { totalCredits, totalHours, courseCount: courses.length };
}
