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

## Live probes

| date       | probe                        | result |
|------------|------------------------------|--------|
| 2026-08-27 | `[LIVE]` GET /menu1/validcode.asp via adapter | HTTP 200, 8982-byte BMP (`BM`), ASPSESSION+BIGip cookies issued — saved `qa/03-validcode.bmp` |
