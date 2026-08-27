#!/usr/bin/env python3
"""Todo-13 live probe: GET /api/stage against the compose app (user-run).

Run this personally AFTER the 加退選一 window opens (2026-08-28 09:00 Asia/Taipei)
against the locally-running compose stack, piping the output to qa/13-live.log:

    docker compose -f deploy/docker-compose.yml up -d          # if not already up
    cd backend && uv run python ../scripts/stage_probe.py --creds-env /path/creds.env

``--creds-env`` honors the capture kit's contract (scripts/capture/creds.py):
a STUDENT_ID/SPASSWORD KEY=VALUE file that lives OUTSIDE the repository and is
owner-readable only (chmod 600). Credentials are memory-only for the login
POST; the student id is masked (``M153****24``) in every line this script
prints, the password is never printed, and the site session cookie value is
never printed. Read-only by construction: the only calls are POST
/api/auth/login and GET /api/stage — nothing reaches the school except the
one Studfun/form GET pair /api/stage itself performs.
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from scripts.capture.creds import CredentialsRejected, load_credentials, mask_student_id  # noqa: E402


def _session_cookie(response: httpx.Response) -> str | None:
    for header in response.headers.get_list("set-cookie"):
        name_value, _, _rest = header.partition(";")
        name, sep, value = name_value.partition("=")
        if sep and name.strip() == "session_id":
            return value.strip()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live todo-13 probe: login + GET /api/stage (masked output)."
    )
    parser.add_argument("--creds-env", type=Path, required=True,
                        help="STUDENT_ID/SPASSWORD env file (outside the repo, chmod 600)")
    parser.add_argument("--base-url", default="http://localhost:8000",
                        help="compose app base URL (default http://localhost:8000)")
    args = parser.parse_args()
    try:
        creds = load_credentials(args.creds_env, repo_root=REPO_ROOT)
    except CredentialsRejected as exc:
        print(f"[CREDS] Refusing: {exc}", file=sys.stderr)
        return 4

    student_id = creds.student_id
    masked = mask_student_id(student_id)
    report: list[str] = []
    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        login = client.post(
            "/api/auth/login",
            json={"student_no": student_id, "password": creds.password},
        )
        del creds  # password's only use is done; drop the reference now
        session_id = _session_cookie(login)
        report.append(f"login: HTTP {login.status_code} (student {masked})")
        if login.status_code != 200 or session_id is None:
            report.append(f"login body: {login.text}")
        else:
            stage = client.get("/api/stage", cookies={"session_id": session_id})
            report.append(f"GET /api/stage: HTTP {stage.status_code}")
            try:
                body = stage.json()
            except ValueError:
                report.append(stage.text)
            else:
                # Student ids stay masked even if a school field ever echoes one.
                for key in ("student_no", "stuid"):
                    if isinstance(body, dict) and key in body:
                        body[key] = masked
                report.append(json.dumps(body, ensure_ascii=False, indent=2))
    # Belt+braces: no raw student id can leak through any of the lines above.
    print("\n".join(report).replace(student_id, masked))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
