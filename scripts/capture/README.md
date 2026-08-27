# Capture kit (todo 4) — pointer

The live-capture CLI does **not** live here; it lives in the backend so it can ride
the backend venv and the selcrs adapter. Run it from `backend/`:

```bash
cd backend && uv run python -m scripts.capture          # --check-window (default)
cd backend && uv run python -m scripts.capture --run    # interactive capture (window only)
```

- Window guard: outside a course-selection window it refuses (exit 2, next window
  start named) and writes the refusal to `qa/04-not-in-window.log`.
- `--run` is interactive and user-run only: it prompts for student id + password via
  `getpass` (memory only, never written anywhere), records fixtures into
  `backend/tests/fixtures/`, appends probe conclusions to `docs/verified-facts.md`
  under `## live-verified (115-1 window)`, and journals to `qa/04-capture.log`.
- Source: `backend/scripts/capture/` (`windows.py` window table, `formparse.py`
  scraping + Big5 submit bodies, `kit.py` interactive protocol, `facts.py` section
  writer). Tests: `backend/tests/test_capture_*.py`.
