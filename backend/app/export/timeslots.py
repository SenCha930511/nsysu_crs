"""NSYSU period-code clock ranges for ICS export (backend mirror of
frontend/src/config/timeslots.ts).

Adapted from NSYSU-OpenDev/NSYSUSelectorHelper (MIT License,
Copyright (c) Cellery Lin and whats2000):
  client-website/src/config.tsx (TIMESLOT)
  https://github.com/NSYSU-OpenDev/NSYSUSelectorHelper

The 15-code alphabet is A,1..4,B,5..9,C,D,E,F with exact Asia/Taipei local
clock ranges. Period code order is canonical (table order), so UID
period-blocks are stable regardless of the raw character order in a day
slot ("65" and "56" describe the same block).
"""

from datetime import time
from typing import Final

# (code, start, end) in chronological order; Asia/Taipei local wall time.
PERIOD_TABLE: Final[tuple[tuple[str, time, time], ...]] = (
    ("A", time(7, 0), time(7, 50)),
    ("1", time(8, 10), time(9, 0)),
    ("2", time(9, 10), time(10, 0)),
    ("3", time(10, 10), time(11, 0)),
    ("4", time(11, 10), time(12, 0)),
    ("B", time(12, 10), time(13, 0)),
    ("5", time(13, 10), time(14, 0)),
    ("6", time(14, 10), time(15, 0)),
    ("7", time(15, 10), time(16, 0)),
    ("8", time(16, 10), time(17, 0)),
    ("9", time(17, 10), time(18, 0)),
    ("C", time(18, 20), time(19, 10)),
    ("D", time(19, 15), time(20, 5)),
    ("E", time(20, 10), time(21, 0)),
    ("F", time(21, 5), time(21, 55)),
)

# code -> (start, end); insertion order = chronological order (canonical).
PERIOD_RANGES: Final[dict[str, tuple[time, time]]] = {
    code: (start, end) for code, start, end in PERIOD_TABLE
}
