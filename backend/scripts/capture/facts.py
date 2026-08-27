"""Writer for the ``## live-verified (115-1 window)`` section of verified-facts.

The section is CREATED on the kit's first --run (docs/verified-facts.md gains
nothing live before that); later runs append a stamped sub-section so window-1
and window-2 captures stay distinguishable. Each probe lands as one bullet
with a CONFIRMED/UNVERIFIED status, per plan todo 4 acceptance.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from scripts.capture.windows import TAIPEI

LIVE_SECTION_HEADER = "## live-verified (115-1 window)"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """One probe conclusion. ``status`` is CONFIRMED or UNVERIFIED, honestly."""

    probe: str
    status: str
    finding: str


def append_live_section(path: Path, window_name: str, results: Sequence[ProbeResult]) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else "# Verified facts\n"
    if LIVE_SECTION_HEADER not in text:
        text = text.rstrip() + f"\n\n{LIVE_SECTION_HEADER}\n"
    stamp = datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M")
    block = [f"### capture run {stamp} (Asia/Taipei) - window {window_name}", ""]
    block.extend(f"- **{result.probe}**: {result.status} - {result.finding}" for result in results)
    path.write_text(text.rstrip() + "\n\n" + "\n".join(block) + "\n", encoding="utf-8")
