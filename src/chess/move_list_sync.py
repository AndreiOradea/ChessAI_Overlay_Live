"""Parse Chess.com / Lichess style move lists and rebuild board state."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple
import chess


_SAN_RE = re.compile(
    r"^(?:"
    r"O-O-O[+#]?"
    r"|O-O[+#]?"
    r"|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?"
    r"|[a-h]x[a-h][1-8](?:=[QRBN])?[+#]?"
    r"|[a-h][1-8](?:=[QRBN])?[+#]?"
    r")$"
)


def extract_san_tokens(text: str) -> List[str]:
    if not text:
        return []
    t = text.replace("\r", "\n")
    t = t.replace("–", "-").replace("—", "-")
    t = t.replace("0-0-0", "O-O-O").replace("0-0", "O-O")
    t = t.replace("o-o-o", "O-O-O").replace("o-o", "O-O")
    tokens: List[str] = []
    for raw in re.split(r"\s+", t):
        raw = raw.strip(" ,;|[]()")
        if not raw:
            continue
        raw = re.sub(r"^\d+\.(\.\.)?", "", raw)
        if not raw or re.fullmatch(r"\d+", raw):
            continue
        if raw in ("1-0", "0-1", "1/2-1/2", "*", "1/2"):
            continue
        if _SAN_RE.match(raw):
            tokens.append(raw)
    return tokens


def replay_moves(
    sans: List[str],
    start_fen: Optional[str] = None,
) -> Tuple[chess.Board, List[str], Optional[str]]:
    board = chess.Board(start_fen) if start_fen else chess.Board()
    applied: List[str] = []
    for san in sans:
        try:
            move = board.parse_san(san)
        except Exception as e:
            return board, applied, f"Failed at '{san}': {e}"
        board.push(move)
        applied.append(san)
    return board, applied, None


def sync_from_text(text: str) -> Tuple[Optional[chess.Board], List[str], str]:
    tokens = extract_san_tokens(text)
    if not tokens:
        return None, [], "No moves found in text"
    board, applied, err = replay_moves(tokens)
    if err:
        return board, applied, f"Synced {len(applied)} moves, then error: {err}"
    side = "White" if board.turn == chess.WHITE else "Black"
    return board, applied, f"Synced {len(applied)} moves · {side} to move"
