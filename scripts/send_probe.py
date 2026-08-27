#!/usr/bin/env python3
"""Todo-15 live probe (user-run, IN-WINDOW only): prove the full write wire
WITHOUT modifying anything real.

  login -> preview ADD of the NONEXISTENT code ZZ999999 -> confirm with the
  freshly re-typed password -> poll the queued job -> expect a SCHOOL-SIDE
  business failure on the audit row. The school is asked to add a course it
  does not have, so it must say no: the wire, the worker, the parser, and
  the audit ledger are all proven live, and the user's selections stay
  untouched by construction.

ZZ999999 is a deliberately nonexistent SCHOOL course code. Our own catalog
would otherwise block it at preview (無課號), so the script seeds ONE
temporary synthetic catalog row (marked QA 探針) into the LOCAL Postgres
before preview and DELETES it in a finally-block — local, reversible, and
never touching the school or any real row.

Run it yourself inside the 加退選一 window (2026-08-28 09:00 ~, Asia/Taipei)
against the compose stack (app+worker must run todo-15 code — rebuild first
if POST /api/write/submit 404s):

    docker compose -f deploy/docker-compose.yml up -d
    uv run --python 3.12 --project backend python scripts/send_probe.py \
      --creds-env /path/to/creds.env

Credentials follow scripts/capture/creds.py: STUDENT_ID/SPASSWORD,
chmod 600, outside the repo. Password is memory-only (re-sent exactly once,
at confirm); the student id prints masked (M153****24); cookie values are
never printed.

Exit codes: 0 expected business failure recorded; 1 flow error; 2 the
school answered something else (job + audit printed for manual reading —
e.g. parse_failed means the provisional response shape drifted).
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from scripts.capture.creds import (  # noqa: E402
    CredentialsRejected,
    load_credentials,
    mask_student_id,
)

PROBE_CODE = "ZZ999999"
COMPOSE = ["docker", "compose", "-f", str(REPO_ROOT / "deploy" / "docker-compose.yml")]
TERMINAL = {"done", "failed", "cancelled", "session_superseded"}


def _psql(sql: str, *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*COMPOSE, "exec", "-T", "postgres", "psql", "-U", "postgres",
         "-d", "nsysu_crs", "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True, text=True, check=check,
    )


def _seed_probe_course() -> None:
    _psql(
        "INSERT INTO courses (year_sem, code, dept, name_zh, credit, restrict,"
        " select_n, selected_n, remaining, class_time, description) VALUES"
        " ('1151', 'ZZ999999', 'QA', 'QA 探針課程（自動清理）', 0, 10, 10, 7, 3,"
        " '[]'::jsonb, 'todo15 send_probe synthetic row; deleted after run')"
        " ON CONFLICT (year_sem, code) DO NOTHING"
    )


def _drop_probe_course() -> None:
    _psql("DELETE FROM courses WHERE year_sem = '1151' AND code = 'ZZ999999'",
          check=False)


def _cookie(response: httpx.Response, name: str) -> str | None:
    for header in response.headers.get_list("set-cookie"):
        name_value, _, _rest = header.partition(";")
        key, sep, value = name_value.partition("=")
        if sep and key.strip() == name:
            return value.strip()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--creds-env", type=Path, required=True,
                        help="STUDENT_ID/SPASSWORD env file (outside the repo, chmod 600)")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    try:
        creds = load_credentials(args.creds_env, repo_root=REPO_ROOT)
    except CredentialsRejected as exc:
        print(f"[CREDS] Refusing: {exc}", file=sys.stderr)
        return 4
    masked = mask_student_id(creds.student_id)
    report: list[str] = [f"send_probe: student {masked}, venue {args.base_url}",
                         f"date {time.strftime('%Y-%m-%d %H:%M %Z')}"]
    exit_code = 1
    seeded = False
    try:
        with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
            probe = client.post("/api/write/submit", json={})
            if probe.status_code == 404:
                report.append("submit endpoint missing (404): rebuild app+worker first")
                raise SystemExit(1)
            health = client.get("/api/health")
            report.append(f"health: {health.status_code} {health.text}")
            if health.status_code != 200:
                raise SystemExit(1)

            _seed_probe_course()
            seeded = True
            report.append(f"seeded local QA catalog row {PROBE_CODE} (deleted after run)")

            login = client.post(
                "/api/auth/login",
                json={"student_no": creds.student_id, "password": creds.password},
            )
            report.append(f"login: HTTP {login.status_code}")
            if login.status_code != 200:
                report.append(f"login body: {login.text}")
                raise SystemExit(1)
            session_id = _cookie(login, "session_id")
            csrf_token = login.json().get("csrf_token")
            if not session_id or not csrf_token:
                report.append("missing session cookie or csrf token after login")
                raise SystemExit(1)
            auth = {
                "cookies": {"session_id": session_id, f"csrf_{session_id}": csrf_token},
                "headers": {"X-CSRF-Token": csrf_token},
            }

            preview = client.post(
                "/api/write/preview",
                json={"ops": [{"action": "+", "course_id": PROBE_CODE, "priority": 1}]},
                **auth,
            )
            report.append(f"preview: HTTP {preview.status_code}")
            if preview.status_code != 200:
                report.append(f"preview body: {preview.text}")
                raise SystemExit(1)
            body = preview.json()
            op = body["ops"][0] if body["ops"] else {}
            report.append(
                f"preview writable={body['writable']} verdict={op.get('verdict')} "
                f"warnings={body['warnings'] + op.get('warnings', [])}"
            )
            if not body["writable"]:
                report.append("preview blocked (unexpected for the seeded probe row)")
                raise SystemExit(1)

            submit = client.post(
                "/api/write/submit",
                json={"confirm_token": body["confirm_token"], "password": creds.password},
                **auth,
            )
            report.append(f"submit: HTTP {submit.status_code}")
            if submit.status_code != 202:
                report.append(f"submit body: {submit.text}")
                raise SystemExit(1)
            job_id = submit.json()["job_id"]
            report.append(f"queued job: {job_id}")

            view: dict = {}
            for _poll in range(120):  # up to 6 minutes; the school queue is FIFO
                view = client.get(f"/api/write/jobs/{job_id}", **auth).json()
                if view["status"] in TERMINAL:
                    break
                time.sleep(3)
            report.append(f"job terminal: {view.get('status')}")
            for item in view.get("ops", []):
                report.append(
                    f"  op {item['action']}{item['code']}: outcome={item['outcome']}"
                    f" msg={item['school_msg']}"
                )
            if view.get("message"):
                report.append(f"  job message: {view['message']}")
            if view.get("reconcile"):
                report.append(f"  reconcile: {view['reconcile']}")

            audit = _psql(
                "SELECT course_id, action, outcome, left(coalesce(school_msg, ''), 80)"
                " AS school_msg_excerpt, left(stuid_hash, 12) AS stuid_hash_head,"
                " created_at FROM write_audit WHERE job_id = "
                f"'{job_id}' ORDER BY created_at",
                check=False,
            )
            report.append("audit row(s), stuid masked by truncation:")
            report.append(audit.stdout.strip() or audit.stderr.strip())

            outcomes = [item["outcome"] for item in view.get("ops", [])]
            if view["status"] == "done" and outcomes == ["failed"]:
                report.append("EXPECTED: the school business-failed the nonexistent "
                              "course - the full wire is proven without touching anything real.")
                exit_code = 0
            else:
                report.append("UNEXPECTED SHAPE: job terminal but outcome is not a plain "
                              "business failure - read the audit above (exit 2).")
                exit_code = 2
    finally:
        if seeded:
            _drop_probe_course()
            report.append(f"deleted QA catalog row {PROBE_CODE}")
    raw_student_id = creds.student_id
    del creds
    # Belt+braces: no raw student id leaks through any of the lines above.
    print("\n".join(report).replace(raw_student_id, masked))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
