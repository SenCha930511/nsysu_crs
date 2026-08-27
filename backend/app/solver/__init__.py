"""Captcha solver service package (plan todo 5): ddddocr OCR + retry loop.

Public surface. Two-layer design: ``ocr.solve`` is the raw ddddocr provider
(raw image bytes in, decoded text out); ``loop.CaptchaLoop`` owns the
fetch-solve-submit retry policy (fresh BMP per attempt, wrong-code markers,
max 5 attempts, per-run cookie jar). ``errors.CaptchaUnsolvable`` is the
terminal signal - a solver accuracy failure, deliberately NOT routed to the
school circuit breaker. The solver callable is injectable at the loop for
tests; importing this package never boots onnxruntime/ddddocr (deferred to
first real solve, proven by tests/test_solver_loop.py).
"""

from app.solver.errors import CaptchaUnsolvable
from app.solver.loop import (
    MAX_SOLVE_ATTEMPTS,
    WRONG_CODE_MARKERS,
    CaptchaLoop,
    CaptchaPageResult,
    is_wrong_code_response,
)
from app.solver.ocr import solve

__all__ = [
    "MAX_SOLVE_ATTEMPTS",
    "WRONG_CODE_MARKERS",
    "CaptchaLoop",
    "CaptchaPageResult",
    "CaptchaUnsolvable",
    "is_wrong_code_response",
    "solve",
]
