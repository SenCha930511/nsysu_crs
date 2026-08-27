"""Out-of-band credential loading for the capture kit (--creds-env).

Contract: credentials may be supplied via a KEY=VALUE env file that lives
OUTSIDE the repository, readable by the owner only. The file must define
``STUDENT_ID`` and ``SPASSWORD``; both are held in memory only and are NEVER
written to any file, log, or journal. Everywhere an identifier must appear
(journal/stdout), it is the MASKED student id (``mask_student_id``); the
password is never printed under any circumstance.

Refusals (``CredentialsRejected``): path resolves inside the repo, file is
group/other-readable (mode bits 0o077 set), file is missing, or required
keys are absent/blank. Refusal messages never echo file contents.
"""

import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REQUIRED_KEYS: Final = ("STUDENT_ID", "SPASSWORD")


class CredentialsRejected(Exception):
    """The creds-env file failed a safety check. Message is content-free."""


@dataclass(frozen=True, slots=True)
class Credentials:
    """Student credentials, memory-only. Never serialized."""

    student_id: str
    password: str


def mask_student_id(student_id: str) -> str:
    """Mask a student id for logs: keep first 4 + last 2 chars (``M153****24``)."""
    if len(student_id) < 6:
        return "****"
    return f"{student_id[:4]}****{student_id[-2:]}"


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines; '#' comments and blank lines are skipped."""
    pairs: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        pairs[key.strip()] = value.strip()
    return pairs


def load_credentials(path: Path, *, repo_root: Path) -> Credentials:
    """Load credentials from ``path`` after the safety checks above.

    ``repo_root`` is the repository the loaded credentials must NOT live in
    (a creds file inside the repo could be committed by accident).
    """
    resolved = path.expanduser().resolve()
    repo_resolved = repo_root.resolve()
    if resolved == repo_resolved or repo_resolved in resolved.parents:
        raise CredentialsRejected(
            f"creds-env path {path} resolves inside the repository - refusing to read it"
        )
    if not resolved.is_file():
        raise CredentialsRejected(f"creds-env file not found: {path}")
    mode = stat.S_IMODE(resolved.stat().st_mode)
    if mode & 0o077:
        raise CredentialsRejected(
            f"creds-env {path} is group/other-readable (mode {mode:04o}); "
            "chmod 600 it first - refusing to read"
        )
    pairs = _parse_env_file(resolved)
    missing = [key for key in REQUIRED_KEYS if not pairs.get(key)]
    if missing:
        raise CredentialsRejected(
            f"creds-env {path} is missing required key(s): {', '.join(missing)}"
        )
    return Credentials(student_id=pairs["STUDENT_ID"], password=pairs["SPASSWORD"])
