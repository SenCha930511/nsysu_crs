"""OCR provider for the captcha solver service (plan todo 5): ddddocr.

The interface is deliberately dpi/shape-agnostic: raw image bytes in (the
school serves 24-bit BMP from menu1/validcode.asp), recognized text out.
Provider is ``ddddocr==1.6.1`` (MIT, exact-pinned in pyproject.toml), running
on onnxruntime - there is NO torch/CapsNet/EfficientCapsNet anywhere in this
project (plan OUT list forbids them; the gate's failure end-state, not a
provider swap, is the remedy if accuracy gates fail).

The ddddocr import is deferred to first use: importing ``app.solver`` (or the
loop that defaults to this solver) must not boot onnxruntime for callers that
inject their own solver, and tests prove injection by asserting ddddocr never
enters ``sys.modules``. ``show_ad=False`` pins the upstream banner off.
"""

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import ddddocr as _ddddocr_types

_engine: "_ddddocr_types.DdddOcr | None" = None
_engine_lock = threading.Lock()


def solve(img_bytes: bytes) -> str:
    """Recognize one captcha image. Raw bytes (BMP/PNG) in, decoded text out."""
    return _get_engine().classification(img_bytes)


def _get_engine() -> "_ddddocr_types.DdddOcr":
    """Process-wide engine, built once. Inference sessions are thread-safe;
    only construction is guarded against concurrent first use."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                import ddddocr

                _engine = ddddocr.DdddOcr(show_ad=False)
    return _engine


__all__ = ["solve"]
