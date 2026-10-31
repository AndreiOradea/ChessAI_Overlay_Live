"""
Screen capture utilities using mss (cross-platform, fast).
"""

from typing import Optional, Tuple
import numpy as np

try:
    import mss
    import mss.tools
except ImportError:
    mss = None

from PIL import Image


class ScreenCapture:
    """Efficient screen region capture."""

    def __init__(self):
        self._sct = None
        if mss is not None:
            self._sct = mss.mss()

    def capture_region(self, x: int, y: int, width: int, height: int) -> Optional[np.ndarray]:
        """
        Capture a screen region and return BGR numpy array (OpenCV format).
        Returns None on failure.
        """
        if self._sct is None:
            return None
        try:
            monitor = {
                "left": int(x),
                "top": int(y),
                "width": int(width),
                "height": int(height),
            }
            shot = self._sct.grab(monitor)
            # mss returns BGRA
            img = np.array(shot)
            # Convert BGRA -> BGR
            if img.shape[2] == 4:
                img = img[:, :, :3]
            return img
        except Exception as e:
            print(f"[ScreenCapture] Error: {e}")
            return None

    def capture_full(self) -> Optional[np.ndarray]:
        """Capture primary monitor."""
        if self._sct is None:
            return None
        try:
            monitor = self._sct.monitors[1]  # Primary
            shot = self._sct.grab(monitor)
            img = np.array(shot)
            if img.shape[2] == 4:
                img = img[:, :, :3]
            return img
        except Exception as e:
            print(f"[ScreenCapture] Full capture error: {e}")
            return None

    def close(self):
        if self._sct is not None:
            self._sct.close()
            self._sct = None
