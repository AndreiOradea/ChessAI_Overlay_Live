"""
OCR the Chess.com (or Lichess) move-list panel from a screen region.
Uses pytesseract when available; otherwise returns empty (user can paste).
"""

from __future__ import annotations

from typing import Optional, Tuple
import numpy as np

_TESS = None
_TESS_TRIED = False


def _get_tesseract():
    global _TESS, _TESS_TRIED
    if _TESS_TRIED:
        return _TESS
    _TESS_TRIED = True
    try:
        import pytesseract
        from pytesseract import pytesseract as pt
        # Common Windows install paths
        import os
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                pytesseract.pytesseract.tesseract_cmd = c
                break
        # probe
        pytesseract.get_tesseract_version()
        _TESS = pytesseract
    except Exception:
        _TESS = None
    return _TESS


def ocr_moves_image(bgr: np.ndarray) -> str:
    """Return raw text from a move-list screenshot (BGR)."""
    tess = _get_tesseract()
    if tess is None or bgr is None or bgr.size == 0:
        return ""
    try:
        import cv2
        from PIL import Image

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        # Upscale for small UI fonts
        h, w = gray.shape[:2]
        scale = 2 if max(h, w) < 600 else 1
        if scale > 1:
            gray = cv2.resize(gray, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
        # Contrast
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Prefer light text on dark (Chess.com dark theme): invert if mostly dark
        if np.mean(bw) < 127:
            bw = 255 - bw
        img = Image.fromarray(bw)
        config = r"--psm 6 -c tessedit_char_whitelist=0123456789.KQRBNakxabcdefghO-+#= "
        text = tess.image_to_string(img, config=config)
        return text or ""
    except Exception as e:
        print(f"[moves_ocr] {e}")
        return ""


def tesseract_available() -> bool:
    return _get_tesseract() is not None
