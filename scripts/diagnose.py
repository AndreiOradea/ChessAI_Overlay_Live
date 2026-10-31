#!/usr/bin/env python3
"""Quick diagnostic for ChessAI Overlay LIVE environment."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def check(name, fn):
    try:
        fn()
        print(f"  [OK]  {name}")
        return True
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        return False

print("ChessAI Overlay LIVE – Environment Check\n")

ok = True
ok &= check("Python >= 3.10", lambda: sys.version_info >= (3, 10) or (_ for _ in ()).throw(Exception(sys.version)))
ok &= check("numpy", lambda: __import__("numpy"))
ok &= check("PIL / Pillow", lambda: __import__("PIL"))
ok &= check("python-chess", lambda: __import__("chess"))
ok &= check("mss", lambda: __import__("mss"))
ok &= check("OpenCV (cv2)", lambda: __import__("cv2"))
ok &= check("PySide6", lambda: __import__("PySide6"))

print()
from src.engine.stockfish_wrapper import StockfishEngine
eng = StockfishEngine()
if eng.engine_path:
    print(f"  [OK]  Stockfish found: {eng.engine_path}")
else:
    print("  [WARN] Stockfish not found in PATH or common locations")
    print("         Download from https://stockfishchess.org/download/")

print()
if ok:
    print("Core dependencies look good. You can run: python main.py")
else:
    print("Some dependencies are missing. Run: scripts\\setup.bat")
