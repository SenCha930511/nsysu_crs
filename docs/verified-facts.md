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
  (source: project research, `.omo/drafts`; live-captured confirmation
  `sso2_fail_*.html` remains **承接 to the 09-09~09-11 加退選(二) capture
  milestone** — deliberately un-run: a wrong-password probe risks the real
  account's lockout budget). Match tolerance: NFKC
  normalization (folds full-width punctuation/digits to half-width) + strip
  all whitespace, then substring search — covers `alert('...')` and
  `<meta http-equiv=refresh>` wrappers and interior spacing.
- **UNKNOWN** = anything else → `SelcrsUnavailable` → circuit breaker input,
  and it is NEVER counted toward the per-account login lockout.
- Redirections are never followed adapter-wide (`follow_redirects=False`):
  the 302 itself is the success signal.

## Big5-HKSCS decoding policy

> **Superseded 2026-08-27** by per-response charset resolution: this "all
> school text is big5hkscs" assumption was live-disproved (the 115-1
> login/read pages are UTF-8 - see *live-verified (115-1)* below).
> `decode.py` now sniffs the charset per response (Content-Type header →
> `<meta>` in the first 2 KiB → strict-UTF-8 heuristic), with big5hkscs as
> the heuristic FALLBACK; every declared `big5` still upgrades to big5hkscs.
> The HKSCS round-trip guarantee and `errors='replace'` below are unchanged.

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
  hard-requires the header remains a probe item **承接到 09-09~09-11
  加退選(二) M-CAPTURE 窗口**（屆時做無 Referer 對照 POST 驗證；無論結果，
  現行「無條件攜帶 Referer」已是較安全的一側，不再調整）。
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
- **Status `2026-08-28` — CLOSED by adjudication:** all 3 batches appended
  (evening `p=0.438` 7/7; late-night `p=0.273` 6/7; window-open `p=0.227`
  5/7; 19/21 pages within budget). Formal gate not met → decision recorded
  in `qa/05-accuracy.log` (tail): **branch A, operational acceptance** —
  production needs exactly 1 captcha/run, 4/4 ingests passed, tick-scale
  self-heal proven; trip-wire = >2 consecutive failed production ticks →
  escalate to user for options B(torch)/C(community JSON).

## Write engine (todo 15) — implementation-pinned facts (2026-08-28)

- **ssprs response shape is PROVISIONAL**: no archived reply exists anywhere
  (checked edwinchu `course_selection_service.dart` at fe64ddb — reads
  only; Hua777 `Req.py`/`Agent.py` — fire-and-forget POST with NO response
  parsing). `backend/tests/fixtures/ssprs_resp_*_provisional.html` and the
  marker vocab in `app/write/response.py` are the archaeological
  expectation (per-course verdict row keyed by 課號); the parser NEVER
  guesses — ambiguity/absence degrade to `parse_failed` with the raw
  excerpt. First live reply comes from `scripts/send_probe.py` in the
  加退選一 window.
- **Worker replay scope**: the engine replays ONLY the scraped hidden
  inputs + `send` (the live form is authoritative at submit time); the
  Studfun-params fallback merge is a preview-side concern (todo 14 shows
  the would-be payload pre-confirm).
- **Outcome enum** (`app/write/outcomes.py`): `success`, `failed` (business,
  terminal), `transport_failed` (after 1+2 engine retries, adapter
  backoff 1s/2s), `parse_failed`, `階段逾時` (session dead or login bounce),
  `unknown-reconciled` (dup-like business failure after a transport retried
  POST; upgraded only by the end-of-job slt_result reconcile — which is
  never retried itself — with `manual_resync_needed` otherwise surfaced in
  the jobs API), `session_superseded`, internal `pending` (fail-closed
  pre-insert placeholder).
- **Audit salt**: `stuid_hash = sha256(APP_SECRET + '|' + student_no)` —
  stable per student for correlation; raw student numbers never written to
  write_jobs/write_audit/queues/logs.
- **Queue mechanics**: Redis-only tickets (`writeq:jobs`, noeviction-pinned
  instance); job row commits BEFORE the RPUSH; worker claims are
  dwell-guarded (WRITE_QUEUE_DWELL_MAX=600 → honest `cancelled`); a lost
  ticket leaves a queued row that the dwell sweep reaps; terminal writes
  are guarded non-terminal-only so a mid-run supersede is never clobbered.
- **Redis-down honesty**: an app-level `RedisError` handler hard-fails
  login + `/api/write/*` with 503 while Postgres reads keep serving
  (qa/15-redisdown.log live matrix).

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

### follow-up 2026-08-27 23:0x (Asia/Taipei) - encoding fix + ONE public catalog probe

- **(g) catalog encoding probe**: CONFIRMED for the probed path —
  `POST /menu1/dplycourse.asp` (public endpoint) with a deliberately-wrong
  `ValidCode=0000`, no login, no captcha spent, ONE request through the
  adapter (legacy TLS + captcha lane) → HTTP **200**, **180-byte** refusal
  page, `Content-Type: text/html` (no charset param), detected charset
  **utf-8** under the new per-response sniffing
  (`backend/scripts/encoding_demo.py --probe-catalog`). Caveat: a 180-byte
  refusal page may be ASCII-only, and ASCII is a UTF-8 subset (heuristic
  branch) — this confirms the refusal page, while captcha-passed dplycourse
  CONTENT pages remain **UNVERIFIED** until a gate batch records one.
  Evidence `qa/03-encoding.log`.
- **(h) decoding-policy fix landed**: `backend/app/selcrs/decode.py`
  resolves charset per response (header → `<meta>` 2 KiB → strict-UTF-8
  else big5hkscs; declared `big5` upgrades to big5hkscs). The finding-(f)
  mis-classification is pinned by fixture tests: the live UTF-8 fail page →
  CREDENTIAL-FAIL, synthetic big5hkscs fail page → CREDENTIAL-FAIL, UTF-8
  302 → SUCCESS, big5hkscs marker-less page → `SelcrsUnavailable`
  (`tests/test_selcrs_encoding_fixtures.py`,
  `tests/test_selcrs_charset.py`); HKSCS round-trip + marker tolerance
  unchanged. Full suite **120 passed** (`qa/03-encoding.log`).

### follow-up 2026-08-28 00:0x–01:0x (Asia/Taipei) - todo 6 live catalog ingest

One full current-D0 ingest through the real pipeline (141 pages, 2596 rows,
327.2s wall, ok=true; evidence `qa/06-live.log`; fixture
`backend/tests/fixtures/dply_page_live_1151.html` + `.txt`).

**(i) Live paging contract (supersedes the provisional "POST ?page=N" assumption):**
page 1 = captcha-spending `POST /menu1/dplycourse.asp` whose URL MUST carry
`?page=1` — a bare POST gets a response whose paging anchors are broken
(`dplycourse.asp&...`, no token); with the query, the footer embeds
`/menu1/dplycourse.asp?a=<server token>&<filter echo>&page=N`. Pages 2..N are
**captcha-free GETs** on those embedded links with the page-1 session jar
(the `a` token binds the result set to that session). Confirmed end-to-end:
page-2 GET → 20 accepted rows, marker "page 2 of 141". Pagination markers:
page footers carry BOTH forms on one line (「第 1 / 141 頁」 + "Showing page 1
of 141 pages"); the parser takes the EN form first. adapter:
`fetch_catalog_page` (POST, `params={"page": 1}`) / `fetch_catalog_page_get`.

**(ii) dplycourse rows and the 8-char course code:** dplycourse has **no
課程代碼 column** — the 8-char `M3046243`-family seen in slt_result col [4]
never appears anywhere in 141 pages (2809 rows). The row's `[4]` is the
variable-length **short 課號** (`STP101`, `CSE515`): 486 stored courses have
8-char short-ids of the same family (`GEAE2526`, `GEPE102T`, `DFLL236A`,
`MEME101B` — sampled via the stored outline URL's `CrsDat=` echo), and
`[17:24]` class_time can carry 8-period full-day strings (`12345678`,
`1234B567`) — neither is a course code. **Conclusion: `courses.code` stays
NULL for every catalog row; identity = the documented fallback
`(year_sem, dept, name_zh, teacher, room, class_time)` (`rows.py`), which the
202-collision in-scrape dedup rate confirmed is granular enough.** Codes
enter the system later from ssform rows at write time (plan: 自 ssform 行補齊).
缺碼行為: write preview marks code-less courses 「無課號」-non-submittable; the
ICS UID degrades to `sha1(year_sem|dept|name_zh|teacher|room|class_time|
weekday|period-block)@nsysu-course-wrapper` (todo 12 slots the fallback
identity into its `code` position), as already specified in the plan.

**(iii) Catalog content charset CONFIRMED = utf-8:** content pages declare
`<meta http-equiv="Content-Type" content="text/html; charset=utf-8">` and
decode cleanly (all 141 pages resolved to `utf-8`; Content-Type header lacks
a charset param, so the meta branch of `resolve_charset` wins). This closes
the finding-(g) caveat: the earlier 180-byte refusal page was ASCII-only and
could not prove anything about content pages. The big5hkscs-decoded fixture
`.txt` shows mojibake exactly because the page is not big5 (capture
convention). big5hkscs remains the right DECODE FALLBACK for undeclared
Big5-era pages, and the HKSCS round-trip guarantee is unchanged.

**(iv) Ingest cost + peak-gate verdict:** wall for a full run = 327.2s
(discovery GET + 1 captcha-parented POST at 4 attempts + 140 sequentially
issued page GETs; avg 2.3s/page after page 1's ~7s solve). Captcha spend per
full 141-page run: 4 attempts on page 1 only (p = 0.25 this run; ongoing
accuracy tracking stays in `qa/05-accuracy.log`). Verdict vs the
`CATALOG_CRON_PEAK` 600s interval: **PASS, no degrade applied** — one
captcha solve + captcha-free GETs leaves ~45% headroom. If school-side peak
latency later blows the budget, the plan's degrade path is changed-depts
diff mode or a longer peak interval plus a meta announcement.

### capture run 2026-08-28 08:58 (Asia/Taipei) - window read-only (anytime)

- **SSO2 tri-state markers (success path)**: CONFIRMED - HTTP 302 + Location contains main_frame + >=1 Set-Cookie observed live (cookie names in qa/04-readonly-capture.log)
- **Studfun closed-state marker**: CONFIRMED - HTTP 200; no ssform/saddstage5 link present (selection closed); observed fragments: 選課關閉 / [選課結果查詢] / 各階段選課結果公布時，請務必上網查看個人選課資料。自92學年度起： / (1) 各階段選課結果公布時，請務必上網查看個人選課資料。 / (2) 加退選結束後，實施「網路確認」正式選課紀錄，未上網確認者，即以教務處所存資料為準。; fixture backend/tests/fixtures/studfun_closed_live_1151.html
- **slt_result column layout vs provisional**: CONFIRMED - live layout 14 cells ['選上 與否', '系所別', '課號', '年級', '課程代碼', '課程名稱', '點數 志願', '階段', '學分', '學年 期', '必選 修', '授課 教師', '教室', '說明'] DIFFERS from provisional assumption (7 cells ['狀態', '課程名稱', '學分', '必選修', '教師', '上課時間', '備註']); fixture backend/tests/fixtures/slt_result_live_1151.html
- **single-session behaviour (does login #2 kill login #1?)**: CONFIRMED - after login #2, login #1's cookie is still ALIVE (school allows concurrent sessions)
- **selcrs session TTL lower bound (>=3 min)**: CONFIRMED - observed marks: +60s=alive, +180s=alive; proves only TTL >= 3 min for this session
- **selcrs session TTL upper/longer bounds**: UNVERIFIED - not probed beyond +180s by design (read-only round scope)
- **SSO2 failure-marker text/variants**: CONFIRMED - marker 「學號碼密碼不符」 hit; observed fragments: 資料錯誤﹕學號碼密碼不符，請重新登錄！; fixture backend/tests/fixtures/sso2_fail_live_1151.html

### capture run 2026-08-28 09:55 (Asia/Taipei) - window read-only (anytime)

- **SSO2 tri-state markers (success path)**: CONFIRMED - HTTP 302 + Location contains main_frame + >=1 Set-Cookie observed live (cookie names in qa/04-readonly-capture.log)
- **Studfun open-state capture (read-only form follow-up)**: CONFIRMED - write link present; fixtures backend/tests/fixtures/studfun_open_live_1151.html + ssform_live_1151.html (15 hidden inputs visible: ['X1', 'X2', 'MAX_ADD', 'DEG_COD', 'college', 'dept', 'grade', 'S_class', 'M_DPT_COD', 'M_DPT_COD2', 'S_DPT_COD', 'EDU', 'SCH_COD', 'USE_YR', 'step']); zero form submissions
- **Studfun closed-state marker**: UNVERIFIED - a write-form link is present (window open) - the closed marker is not observable this round
- **slt_result column layout vs provisional**: CONFIRMED - live layout 14 cells ['選上 與否', '系所別', '課號', '年級', '課程代碼', '課程名稱', '點數 志願', '階段', '學分', '學年 期', '必選 修', '授課 教師', '教室', '說明'] DIFFERS from provisional assumption (7 cells ['狀態', '課程名稱', '學分', '必選修', '教師', '上課時間', '備註']); fixture backend/tests/fixtures/slt_result_live_1151.html
- **single-session behaviour (does login #2 kill login #1?)**: CONFIRMED - after login #2, login #1's cookie is still ALIVE (school allows concurrent sessions)
- **selcrs session TTL lower bound (>=3 min)**: CONFIRMED - observed marks: +60s=alive, +180s=alive; proves only TTL >= 3 min for this session
- **selcrs session TTL upper/longer bounds**: UNVERIFIED - not probed beyond +180s by design (read-only round scope)
- **SSO2 failure-marker text/variants**: CONFIRMED - marker 「學號碼密碼不符」 hit; observed fragments: 資料錯誤﹕學號碼密碼不符，請重新登錄！; fixture backend/tests/fixtures/sso2_fail_live_1151.html

### write-path run 2026-08-28 10:30 (Asia/Taipei) - 115-1 加退選一 window (bogus-code writes only)

- **ssform submit endpoint**: CONFIRMED - the live ssform's STATIC form action is the 暫存/draft endpoint (`ssform.asp`); the real 送出 submit is pinned by the 送出 button's onclick JS (`f1.action='ssprs.asp'` + injected `step=2`). Posting to the static action re-renders the form (the 2026-08-28 10:04 probe's parse_failed root cause). Fixture backend/tests/fixtures/ssform_live_1151.html.
- **REAL ssprs failure-response shape**: CONFIRMED - a status-SNAPSHOT page (姓名/學號 header, 【目前選課紀錄】 current-selections table) followed by an `<hr>`-separated failure section headed 【加退選失敗課程清單】. A bogus/unknown course code is rejected at BATCH level: the failure section header is present but the op's code is NOT itemized anywhere on the page. Fixture backend/tests/fixtures/ssprs_resp_addfail_live_1151.html (+ sent wire body ssprs_post_body_addfail_live_1151.txt). Whether real validation failures (額滿/衝堂/必修) are itemized per code: UNVERIFIED (only the nonexistent-code probe is legally writable).
- **end-to-end write wire**: CONFIRMED - login -> preview(200) -> submit(202) -> worker -> job DONE with per-op audit outcome=failed, school_msg=【加退選失敗課程清單】 for the nonexistent ZZ999999 add (qa/15-live.log, SEND_EXIT=0). Zero modification to real selections by construction.

### identifier probe run 2026-08-28 14:0x (Asia/Taipei) - read-only, live session jar

- **Write-form identifier = 課別代號**: CONFIRMED - `GET chk_crsno_desc.asp?ACTION=1&SYEAR=115&SEM=1&CRSNO=CSE515` resolves `{"data":[{"T_NAME":"林俊宏","CRS_DESC":"高等電腦網路",...}]}` while `CRSNO=M3046243` (課程代碼) returns `{"RESULT":"NODATA!!"}`. Evidence qa/probe-crsno-desc.txt. Consequent semantics: the C slot of ssprs/stage5 replay must carry 課別代號; catalog.code now holds exactly that value (derived from each row's own showoutline `CrsDat=` - zero school traffic; schema widened CHAR(8)→VARCHAR(20), revision 0002_course_code_varchar20, 2596/2596 backfilled).
- **Selections drops are self-identifying**: the "-" op identity comes from the student's own selection `course_no` (slt_result column 2) which equals the catalog CrsDat form; drops of catalog-absent courses stay submittable (preview falls back to the selections membership set).
