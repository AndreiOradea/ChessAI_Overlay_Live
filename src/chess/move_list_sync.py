from __future__ import annotations
import re
from typing import List, Optional, Tuple
import chess

_SAN_RE = re.compile(
    r"^(?:O-O-O[+#]?|O-O[+#]?|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?|[a-h]x[a-h][1-8](?:=[QRBN])?[+#]?|[a-h][1-8](?:=[QRBN])?[+#]?)$"
)


def extract_san_tokens(text: str) -> List[str]:
    if not text:
        return []
    t = text.replace("\r", "\n").replace("–", "-").replace("—", "-")
    t = t.replace("0-0-0", "O-O-O").replace("0-0", "O-O")
    tokens = []
    for raw in re.split(r"\s+", t):
        raw = raw.strip(" ,;|[]()")
        raw = re.sub(r"^\d+\.(\.\.)?", "", raw)
        if not raw or re.fullmatch(r"\d+", raw):
            continue
        if raw in ("1-0", "0-1", "1/2-1/2", "*", "1/2"):
            continue
        if _SAN_RE.match(raw):
            tokens.append(raw)
    return tokens


def sync_from_text(text: str) -> Tuple[List[str], str]:
    tokens = extract_san_tokens(text)
    if not tokens:
        return [], "No moves found"
    board = chess.Board()
    applied = []
    for san in tokens:
        try:
            board.push_san(san)
            applied.append(san)
        except Exception as e:
            return applied, f"Synced {len(applied)}, failed at {san}: {e}"
    side = "White" if board.turn else "Black"
    return applied, f"Synced {len(applied)} moves · {side} to move"
