# ChessAI Overlay LIVE

**Universal chess companion overlay for Windows 10 & Windows 11**

A real desktop always-on-top overlay that works with Chess.com, Lichess, browser-based chess, and most desktop chess applications via screen recognition.

---

## Features

### Universal Board Recognition
- Manual screen-region selector (works with any platform)
- Automatic detection of board location, orientation, squares and pieces
- Support for multiple board themes, sizes, piece sets and both orientations
- Live FEN tracking + manual FEN correction
- Confidence scoring – asks for correction instead of guessing when unsure

### Always-on-top Overlay
- Compact floating panel, dark charcoal + purple accent theme
- Adjustable transparency, size and position (draggable)
- Hide / show, minimize, pin controls
- Live connection & board-recognition status indicators

### Modes

| Mode | Engine | Intended use |
|------|--------|--------------|
| **LIVE** | OFF | Competitive / rated games (fair-play) |
| **LIVE ENGINE** | ON (real-time) | Offline, private analysis, matches where engine help is explicitly allowed |
| **TRAINING** | ON | Interactive training |
| **ANALYSIS** | ON | Post-game deep review |

#### LIVE Mode (Fair-Play Aware)
| Allowed | Not Allowed |
|---------|-------------|
| Board recognition & position tracking | Stockfish best moves |
| Move history (algebraic notation) | Engine evaluations |
| Legal-move validation | Principal variations |
| Personal tactical checklist | Any engine suggestions |
| Position recording for later review | |

#### LIVE ENGINE Mode (Authorized games only)
- Real-time board recognition + automatic Stockfish on every change
- Best move, evaluation, top-3 candidates, principal variation
- Move arrows drawn over the board
- Hanging pieces & tactical threats
- Adjustable depth, time, threads, hash
- **Never** automates moves or sends moves to any server
- User must consciously select this mode (not the default)

### Training & Post-Game Analysis
- Full Stockfish integration via UCI
- Best moves, candidate moves, centipawn & mate scores
- Configurable depth, time, threads, hash
- Principal variations
- Blunder / mistake / inaccuracy detection (via analysis)
- Opening identification helpers
- Move-by-move review of completed games
- PGN import / export
- Review of positions recorded during LIVE mode (subject to platform rules)

### Architecture
- **Python 3.10+** + **PySide6** (desktop GUI)
- **OpenCV** + **mss** for screen capture & board vision
- **python-chess** for FEN, SAN, PGN, legality
- **Stockfish** (UCI) for LIVE ENGINE / Training / Analysis
- Asynchronous workers keep the overlay responsive
- Local JSON config + saved games

---

## Quick Start (Windows)

### 1. Prerequisites
- Windows 10 or 11
- Python 3.10 or newer → https://www.python.org/downloads/  
  (check “Add Python to PATH” during install)

### 2. Setup
```bat
cd ChessAI_Overlay_LIVE
scripts\setup.bat
```

### 3. Install Stockfish (required for LIVE ENGINE, Training, Analysis)
1. Download the latest Windows binary from https://stockfishchess.org/download/
2. Extract `stockfish.exe` to a folder, e.g. `C:\stockfish\`
3. The app will auto-detect common locations. You can also set the path later.

### 4. Launch
```bat
scripts\launch.bat
```
or
```bat
python main.py
```

### 5. First-time use
1. Click **Select Region**
2. Drag a rectangle tightly around the chessboard on your screen
3. The overlay begins tracking the position
4. Use **Flip** if the board orientation is wrong
5. Correct the FEN manually if recognition is imperfect

---

## Building a Standalone Executable

```bat
scripts\build_exe.bat
```

The executable will appear in `dist\ChessAI_Overlay_LIVE\`.  
You still need Stockfish separately for engine features.

---

## Project Structure

```
ChessAI_Overlay_LIVE/
├── main.py                 # Entry point
├── requirements.txt
├── README.md
├── src/
│   ├── ui/
│   │   └── overlay.py      # Always-on-top panel + region selector
│   ├── recognition/
│   │   └── board_detector.py
│   ├── chess/
│   │   └── game_tracker.py
│   ├── engine/
│   │   └── stockfish_wrapper.py
│   └── utils/
│       ├── config.py
│       └── screen_capture.py
├── tests/
│   ├── test_board_detector.py
│   ├── test_game_tracker.py
│   └── test_engine.py
└── scripts/
    ├── setup.bat
    ├── launch.bat
    └── build_exe.bat
```

---

## Configuration

User settings are stored in:
```
%USERPROFILE%\.chessai_overlay\config.json
```

Saved games and logs live in the same folder.

---

## Running Tests

```bat
call venv\Scripts\activate.bat
pytest tests/ -v
```

Engine tests are automatically skipped if Stockfish is not found.

---

## Fair-Play Policy

This application is designed to **respect** the rules of chess platforms:

- In **LIVE** mode the engine is completely disabled for move suggestions.
- The overlay does **not** inject scripts into browsers, does **not** read private APIs, and does **not** automate mouse/keyboard input for moves.
- Board recognition is purely visual (screen capture).
- Users remain responsible for complying with the terms of service of Chess.com, Lichess, or any other platform they use.

Using engine assistance during rated or competitive games where it is prohibited is cheating. This tool does not encourage or facilitate that.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| “No board” / low confidence | Re-select a tighter region around the board only. Avoid including clocks or player names. |
| Wrong orientation | Click **Flip**. |
| Pieces misidentified | Use the FEN box to correct the position manually. Recognition improves with clearer boards. |
| Overlay not on top | Click the pin button. |
| Stockfish not found | Download from stockfishchess.org and place `stockfish.exe` in a standard location or set the path. |
| Capture fails on multi-monitor | Make sure the board is on the primary monitor or adjust coordinates. |
| High CPU | Lower capture FPS in config (default 4 FPS is usually enough). |

### Improving Recognition Accuracy
The included piece classifier is intentionally simple and conservative so it never invents pieces. For higher accuracy you can later replace the heuristic classifier in `board_detector.py` with:
- Template matching against the specific piece set you use
- A small CNN trained on screenshots of your preferred themes

---

## Limitations (Honest Status)

- Automatic piece-type recognition is **heuristic** and works best on high-contrast classic piece sets. Always verify critical positions with the FEN field.
- Clock reading is not yet implemented (placeholder only).
- Platform-specific APIs (official Chess.com / Lichess game export) are not yet wired; the universal screen-recognition path is the primary method.
- The application has been designed for reliability and fair-play compliance first. Feature depth will grow with testing on real boards.

---

## License & Credits

- Built with PySide6, OpenCV, python-chess, mss, Stockfish.
- Stockfish is licensed under GPLv3 – you must comply with its license when distributing.
- This project is provided as-is for educational and personal use.

---

**Enjoy your games – and stay fair.**
