# Verified facts — selcrs / NSYSU course system

Ground facts the backend relies on, each with its source. `[LIVE]` entries are
empirically confirmed against the school host; the rest are archaeological
(pinned by MIT-licensed reference code) until the todo-4 capture window
records them live. Spec authority: `.omo/plans/nsysu-course-wrapper.md`.

## SSO2 password transform: `base64md5`

**Source:** NsysuApp `Utils.base64md5` —
https://raw.githubusercontent.com/edwinchu0711/NsysuApp_OpenSource/fe64ddb64df76614fc406a7ec2b6694af26c75d6/lib/utils/utils.dart
(commit `fe64ddb64df76614fc406a7ec2b6694af26c75d6`, 2026-08-20; MIT, (c) 2026 Edwin Chu)

Dart original (copied byte-for-byte into `backend/app/selcrs/transform.py`):

```dart
static String base64md5(String text) {
  var bytes = utf8.encode(text);       // 1. UTF-8 encode
  var digest = md5.convert(bytes);     // 2. MD5 -> raw 16-byte digest
  return base64.encode(digest.bytes);  // 3. std padded Base64 of RAW digest bytes
}
```

Transform: `base64( standard alphabet, padded )( md5( utf8( password ) ).raw_bytes )`.
It is NOT Base64 of the 32-char hex digest (locked by the second vector test).

Test vectors (locked in `tests/test_selcrs_transform.py`; reproducible via
`printf %s "<input>" | openssl md5 -binary | openssl base64`):

| input      | output (SPassword)         |
|------------|----------------------------|
| `123456`   | `4QrcOUm6Wau+VuBX8g+IPg==` |
| `654321`   | `wzNncBURtPYCDsYd7TUgWQ==` |
| (empty)    | `1B2M2Y8AsgTpgAmY7PhCfg==` |

## SSO2 endpoint + tri-state contract

- `POST https://selcrs.nsysu.edu.tw/menu4/Studcheck_sso2.asp` with form fields
  `stuid=<student_no>`, `SPassword=base64md5(password)`. No captcha.
- **SUCCESS** = HTTP 302 AND `Location` contains `main_frame` AND ≥1 `Set-Cookie`.
- **CREDENTIAL-FAIL** = HTTP 200 AND body contains 「學號碼密碼不符」
  (source: project research, `.omo/drafts`; live-captured confirmation is a
  todo-4 deliverable, `sso2_fail_*.html` *PENDING*). Match tolerance: NFKC
  normalization (folds full-width punctuation/digits to half-width) + strip
  all whitespace, then substring search — covers `alert('...')` and
  `<meta http-equiv=refresh>` wrappers and interior spacing.
- **UNKNOWN** = anything else → `SelcrsUnavailable` → circuit breaker input,
  and it is NEVER counted toward the per-account login lockout.
- Redirections are never followed adapter-wide (`follow_redirects=False`):
  the 302 itself is the success signal.

## Big5-HKSCS decoding policy

- All school text responses are decoded as **big5hkscs** with
  `errors='replace'` (`backend/app/selcrs/decode.py`), never plain `big5`.
  Rationale `[LIVE-in-tests]`: teacher/student names contain HKSCS-only
  characters such as 「喆」 — plain `big5` cannot even ENCODE 「喆」
  (UnicodeEncodeError), while `big5hkscs` round-trips it losslessly.
- `errors='replace'` bounds blast radius: one bad byte turns into U+FFFD at
  that position instead of killing a 30k-row catalog ingest; decoding
  continues after the bad span. Asserted in `tests/test_selcrs_big5hkscs.py`.
- Binary payloads (validcode BMP) are never decoded.

## TLS policy (legacy school front-end)

Every school client gets a dedicated `ssl.SSLContext` with
`ssl.OP_LEGACY_SERVER_CONNECT` (0x4) + `set_ciphers("DEFAULT@SECLEVEL=1")`
(`backend/app/selcrs/http.py`). Scoped to the school context only.
**Proven `[LIVE]` 2026-08-27**: the adapter itself fetched a captcha —
`qa/03-validcode.bmp`, 8982 bytes, magic `BM`, ~0.27s.

## Throttle / backoff numbers

- Global cap: **2 concurrent** school requests (process-wide semaphore)
  covering **every** adapter call to the school; the school front-end is
  fragile at selection-window peak.
- Captcha-related requests (validcode fetches **and** the `dplycourse.asp`
  POSTs that spend the solved code) additionally hold a **separate
  semaphore of 1** (fully serialized process-wide), taken **on top of** —
  never instead of — the global cap, so school-wide concurrency never
  exceeds 2. Per-run cookie jar: concurrent catalog runs never share a jar
  (all asserted in `tests/test_selcrs_throttle.py`).
- Transport errors/timeouts: attempts with waits exactly **1, 2, 4, 8, 16s**
  (5 attempts), then `SelcrsUnavailable`. HTTP-level outcomes are not retried
  here (business retry policy = todo 15).
- Timeouts: connect 10s / read 30s / write 10s / pool 30s.

## Write-path POST policy

- Write-path POSTs (todo 14/15 style) always carry
  `Referer: <same-session GET form URL>` — sent unconditionally at the adapter
  (`post_write(..., referer=...)` is a mandatory argument). Whether the school
  hard-requires the header is a todo-4 probe item *PENDING*.
- Chinese-text catalog form fields (`teacher`/`crsname`) are pinned empty at
  the adapter payload builder; enumeration is by codes only.

## Captcha solver: ddddocr pin + gate methodology (todo 5)

- **Provider:** `ddddocr==1.6.1` (exact pin in `backend/pyproject.toml` and
  `backend/uv.lock`; install evidence `qa/05-pin.log`). Runs on onnxruntime
  (deps: numpy, onnxruntime, opencv-python, pillow) — **no torch/CapsNet/
  EfficientCapsNet** anywhere, per the plan's OUT list.
- **Solver boundary:** raw image bytes in → decoded text out
  (`app/solver/ocr.py: solve(img_bytes) -> str`); engine built lazily on
  first solve with `show_ad=False`; provider injectable at the loop.
- **Loop contract** (`app/solver/loop.py`): fresh BMP → solve → submit; a
  response containing `Wrong Validation Code` / 「驗證碼錯誤」 (NFKC-folded,
  whitespace-stripped substring match, alert()/meta wrappers tolerated)
  triggers a re-fetch of a FRESH BMP into the SAME per-run jar lineage; the
  5th rejection raises `CaptchaUnsolvable` exactly once (no 6th attempt).
  Mock evidence: `qa/05-loop.log`, jar isolation `qa/05-jariso.log`.
- **Gate methodology** (`backend/scripts/captcha_gate.py --pages N`):
  N consecutive LIVE public-catalog pages through the loop (no login;
  `dplycourse.asp` with `D0=<year_sem>`, WKDAY rotating 1..7 for distinct
  slices). Measures captcha accuracy only — row/pagination parsing is todo
  6 and is deliberately not done. Each batch APPENDS one evidence block to
  `qa/05-accuracy.log`: per-attempt outcomes, per-depth accepted/reached,
  per-attempt success rate p (= accepted submissions / total submissions),
  worst retries-per-page, PASS/FAIL on the ≤5-attempts-per-page budget.
  Plan gate: ≥20 pages across ≥3 time slots, 100% of pages within budget.
- **Status `2026-08-27`:** batch 1/3 (evening) appended — 7/7 pages within
  budget (worst 4), but p = 0.438 < 50% → recorded as gate-risk pending
  batches 2–3 and the user/decision branch for the accuracy remedy.

## Live probes

| date       | probe                        | result |
|------------|------------------------------|--------|
| 2026-08-27 | `[LIVE]` GET /menu1/validcode.asp via adapter | HTTP 200, 8982-byte BMP (`BM`), ASPSESSION+BIGip cookies issued; ddddocr 1.6.1 solved the saved BMP offline as `7995` — saved `qa/03-validcode.bmp` |
| 2026-08-27 | `[LIVE]` captcha gate batch 1/3 (evening), `--pages 7` | 7/7 pages ≤5 attempts, 0 `CaptchaUnsolvable`, worst 4 retries; per-attempt p = 0.438 (16 attempts / 7 accepted) — `qa/05-accuracy.log` |
