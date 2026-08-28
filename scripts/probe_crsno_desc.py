#!/usr/bin/env python3
"""Read-only identifier probe: chk_crsno_desc.asp<unknowable-js-endpoint>.

Settles one question cheaply and identifiably: WHICH course identifier does
the school's write form (ssform C-field) accept — the 課別代號 (CSE515) or
課程代碼 (M3046243)? The console's add-flow depends on the answer.

Contract:
- READ-ONLY: exactly 2 GETs against the school's own client-side descriptor
  endpoint (the same one the school's own JS calls on every blur of the C
  input). Zero POSTs, zero selection mutations - nothing to restore.
- Uses the freshest site session's school jar from Redis (no credentials are
  needed, never read, never printed).
- Output artifact is byte-masked (M153****24) defensively.

Run against the compose deployment (school session kept alive by the UI):
    docker compose -f deploy/docker-compose.yml cp scripts/probe_crsno_desc.py worker:/tmp/
    docker compose -f deploy/docker-compose.yml exec -T worker \
      sh -lc 'cd /app && uv run python /tmp/probe_crsno_desc.py'
Exit 0 = both probes answered; artifacts at/qa/ require repo path outside.
"""

import asyncio
import os
from pathlib import Path

import httpx
import redis.asyncio as aioredis

BASE = "https://selcrs.nsysu.edu.tw/menu4/addcourse/"
PROBE_VALUES = ("CSE515", "M3046243")
OUT = Path("/tmp/probe_crsno_desc.txt")


async def freshest_jar(r: aioredis.Redis) -> tuple[str, list[dict[str, str]]]:
    import json

    best: tuple[int, str] | None = None
    cursor = 0
    while True:
        cursor, keys = await r.scan(cursor, match="selcrs:*", count=200)
        for key in keys:
            k = key if isinstance(key, str) else key.decode()
            if k.endswith("_hard") or ":hard" in k.split(":")[1] or k.startswith("selcrs_hard"):
                continue
            ttl = await r.ttl(k)
            if isinstance(ttl, int) and ttl > 0 and (best is None or ttl > best[0]):
                best = (ttl, k)
        if cursor == 0:
            break
    if best is None:
        raise SystemExit("no live selcrs jar in redis (site session expired?)")
    payload = await r.get(best[1])
    if payload is None:
        raise SystemExit(f"jar {best[1]} vanished mid-read")
    rows = json.loads(payload)
    jar = [{"name": name, "value": value} for name, value in rows]
    return best[1], jar


async def main() -> None:
    r = aioredis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"))
    key, jar = await freshest_jar(r)
    print(f"[probe] using jar from {key} (ttl unknown, freshest)", flush=True)
    cookies = {row["name"]: row["value"] for row in jar}
    lines: list[str] = []
    async with httpx.AsyncClient(cookies=cookies, timeout=20.0, base_url=BASE) as client:
        for value in PROBE_VALUES:
            resp = await client.get(
                "chk_crsno_desc.asp", params={"ACTION": "1", "SYEAR": "115", "SEM": "1", "CRSNO": value},
            )
            body = resp.text
            lines.append(f"== {value} == status={resp.status_code} len={len(body)}")
            lines.append(body[:1200])
            await asyncio.sleep(1.0)
    masked = "\n".join(lines)
    for secret in (os.environ.get("STUDENT_ID", ""),):
        if secret:
            masked = masked.replace(secret, "M153****24")
    OUT.write_text(masked + "\n", encoding="utf-8")
    print(f"[probe] wrote {OUT}", flush=True)
    await r.aclose()


if __name__ == "__main__":
    asyncio.run(main())
