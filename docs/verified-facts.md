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

## live-verified (115-1)

### capture run 2026-08-27 22:47 (Asia/Taipei) - read-only round (anytime; NO window guard)

Strictly read-only: 8 outbound calls total — 3 SSO2 login POSTs (2 real +
1 deliberately-wrong password, exactly once) and 5 pure GET reads
(`Studfun.asp`, `query/slt_result.asp`). No add/drop/selection write of any
kind, no ssprs/form POST, no replay probe, no course code submitted; per-call
justifications in `qa/04-readonly-capture.log`. Fixtures saved as raw bytes
`.html` + big5hkscs-decoded `.txt` (see the encoding finding below: the `.txt`
files therefore show mojibake — the raw `.html` bytes are ground truth).
Student id masked in-place as `M153****24` inside the slt_result fixture.

- **(a) SSO2 success wire shape / tri-state SUCCESS rule**: CONFIRMED —
  `POST /menu4/Studcheck_sso2.asp` with real credentials → HTTP **302**,
  `Location: main_frame.asp` (relative, no query string, no id), Set-Cookie
  names `ASPSESSIONIDxxxxxxxx` (suffix varies per session), `BIGipServerPL-Selcrs`,
  `TS01b534ab` (values never recorded). Matches the SUCCESS rule
  (302 + `main_frame` in Location + ≥1 Set-Cookie) exactly; evidence
  `qa/04-readonly-capture.log`.
- **(b) Studfun CLOSED-state real marker**: CONFIRMED — outside a window the
  page renders the literal heading 「**選課關閉**」 and offers only the links
  【選課結果查詢】【選課相關資訊】【教學意見即時回饋系統】【個人工具箱】【離開選課系統】 –
  NO `ssform.asp`/`saddstage5.asp` href anywhere. Closed-state detection =
  that heading + absence of a write-form link. Fixture
  `backend/tests/fixtures/studfun_closed_live_1151.html` (1734 bytes).
- **(c) slt_result real column layout**: CONFIRMED — **14 columns**, differing
  from the provisional 7-column assumption (`狀態/課程名稱/學分/必選修/教師/上課時間/備註`):
  `[0]選上與否 [1]系所別 [2]課號 [3]年級 [4]課程代碼 [5]課程名稱 [6]點數志願
  [7]階段 [8]學分 [9]學年期 [10]必選修 [11]授課教師 [12]教室 [13]說明`.
  Notes vs the assumption: `[2]課號` is the short code (e.g. `CSE515`),
  `[4]課程代碼` is the 8-char code (e.g. `M3046243`); there is **no 上課時間
  column** — `[12]教室` fuses weekday/periods+room (e.g. `三2,3,4(工EC 5012)`);
  status rows are pre-sectioned by a banner row (e.g. `※ ※ 選上課程 ※ ※`).
  Fixture `backend/tests/fixtures/slt_result_live_1151.html` (16523 bytes,
  student id masked). Provisional 7-column fixture superseded for parser work.
- **(d) single-session behaviour**: CONFIRMED — after a SECOND SSO2 login,
  the FIRST session's cookie on `slt_result` is still **ALIVE** (HTTP 200 real
  page, not bounced to login). The school allows concurrent sessions; the
  todo-8 `SESSION_SUPERSEDED` rule can rely on school-side coexistence
  (session replacement must remain a site-side policy). Evidence
  `qa/04-readonly-capture.log`.
- **(e) session-TTL bound**: lower bound CONFIRMED — `slt_result` alive at
  **+60s and +180s** after login #1 (probes ran on jar1, which survived the
  second login) → TTL ≥ 3 min for this session. Longer/upper bounds
  UNVERIFIED (not probed beyond +180s by design). Evidence
  `qa/04-readonly-capture.log`.
- **(f) SSO2 failure page (wrong password, 1 attempt)**: CONFIRMED — HTTP
  **200**, no `Location`, session cookies still issued. Exact failure text,
  decoded per the page's actual UTF-8 bytes (see encoding finding):
  「**資料錯誤﹕學號碼密碼不符，請重新登錄！**」 (full-width colon `﹕`; rendered
  as plain top-of-body text, no alert() wrapper this variant). The
  archaeological marker substring 「學號碼密碼不符」 IS contained in that text.
  **Adapter impact (real bug found): under the current all-big5hkscs decode
  policy this live failure decodes to mojibake, the marker does NOT match, and
  the attempt would be mis-classified UNKNOWN (breaker) instead of
  CREDENTIAL-FAIL.** Fixture `backend/tests/fixtures/sso2_fail_live_1151.html`
  (295 bytes). Failure-marker variants observed live: exactly the one string
  above; Big5-era variants (alert()/meta-refresh wrappers, full/half-width
  variants) NOT observed this round — remain archaeological.
- **decoding-policy correction (cross-cutting)**: CONFIRMED for tonight's
  three login/read pages — `Studfun.asp`, `query/slt_result.asp`, and the
  SSO2 failure page all declare `charset=utf-8` in their `<meta>` AND are
  valid UTF-8 bytes on the wire (no BOM); big5hkscs decoding yields the
  mojibake shown in the saved `.txt` files. The "all school text is
  big5hkscs" assumption (see *Big5-HKSCS decoding policy* above) is therefore
  WRONG for these endpoints as of 2026-08-27; the decode layer must detect
  encoding per response (e.g. trust the page's declared charset / try UTF-8
  first) before the SSO2 classifier and the slt_result/Studfun parsers can be
  trusted live. Catalog endpoints (`validcode.asp`/`dplycourse.asp`) were NOT
  in tonight's read-only scope: their encoding remains **UNVERIFIED** (the
  validcode BMP itself is binary and unaffected).
