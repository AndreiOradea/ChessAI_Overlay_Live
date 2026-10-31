from __future__ import annotations
from typing import Optional
import numpy as np

try:
    import mss
except ImportError:
    mss = None


class ScreenCapture:
    def __init__(self):
        self._sct = mss.mss() if mss else None

    def capture_region(self, x: int, y: int, w: int, h: int) -> Optional[np.ndarray]:
        if not self._sct or w <= 0 or h <= 0:
            return None
        try:
            shot = self._sct.grab({"left": int(x), "top": int(y), "width": int(w), "height": int(h)})
            img = np.array(shot)
            if img.shape[2] == 4:
                img = img[:, :, :3]
            return img
        except Exception as e:
            print(f"[capture] {e}")
            return None

    def close(self):
        if self._sct:
            self._sct.close()
            self._sct = None
