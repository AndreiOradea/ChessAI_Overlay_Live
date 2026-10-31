<p align="center">
  <img src="favicon.png" alt="Logo" width="110"/>
</p>

<h1 align="center">♟️ ChessAI Overlay LIVE</h1>

<p align="center">
  <b>Windows chess companion</b> — always-on-top overlay, live board mirror & optional Stockfish analysis
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Windows-10%20%2F%2011-0078D6?style=for-the-badge&logo=windows&logoColor=white"/>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/UI-PySide6-41CD52?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Engine-Stockfish-1B5E20?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge"/>
</p>

<p align="center">
  <img src="x-banner.jpg" alt="Banner" width="100%"/>
</p>

<p align="center">
  <img src="og.jpg" alt="Preview" width="680"/>
</p>

---

## ✨ What it does

ChessAI Overlay LIVE is a **real desktop app** (not a browser extension).

It sits on top of your game, reads the board from a screen region you select, mirrors the position on an **internal chessboard**, and can run **Stockfish** analysis with evaluation, best move and arrows — for training and authorized games only.

| 🟢 Does | 🔴 Does not |
|--------|-------------|
| Track the live position from screen | Inject scripts into Chess.com / Lichess |
| Show BEST moves on the **in-app board** | Auto-move or click pieces for you |
| Work with browser & desktop chess | Send moves to any server |
| Offer a fair-play **LIVE** mode (engine off) | Encourage cheating in rated games |

---

## 🎯 Features

### 📺 Screen board tracking
- **Select Board Region** — drag over the 8×8 board
- Move detection after the piece is **fully placed** (ignores drag animations)
- Built for **Classic** piece sets (best accuracy)
- **Flip** board orientation (White / Black at bottom)
- **I play: White / Black** — labels the side to move as yours or your opponent's

### 🧩 Internal chessboard
- Live copy of the game inside the app
- **Edit Position** — drag pieces freely; right-click a square to add/remove a piece or set whose turn it is
- Last move highlight
- Purple / green **BEST move** arrows on the internal board
- Move list + side to move

### 🧠 Engine (LIVE ENGINE mode)
- Stockfish evaluation (e.g. `+0.36`)
- Best move + top candidate lines
- Adjustable depth & think time
- **Analyze** button — resync from screen + fresh analysis
- Async engine so the UI stays responsive

### 🎮 Modes

| Mode | Engine | Best for |
|------|--------|----------|
| **LIVE** | ❌ Off | Rated / competitive games |
| **LIVE ENGINE** | ✅ On | Vs computer, training, allowed analysis |

---

## 🚀 Quick start

### Requirements
- Windows 10 or 11  
- [Python 3.10+](https://www.python.org/downloads/) → enable **Add to PATH**

### Install

```bat
git clone https://github.com/AndreiOradea/ChessAI_Overlay_Live.git
cd ChessAI_Overlay_Live
scripts\setup.bat
```

### Stockfish
1. Download: [stockfishchess.org/download](https://stockfishchess.org/download/)  
2. Put `stockfish*.exe` in a `stockfish\` folder  
3. Restart the app

### Run

```bat
scripts\launch.bat
```

or:

```bat
python main.py
```

### First game
1. Chess.com → **Classic** pieces (not Neo)  
2. Start a **new** game from move 1  
3. App → **Reset** → **Select Board Region**  
4. **I play: White** (or Black)  
5. Mode: **LIVE ENGINE**  
6. Move, release the piece, wait ~1 second  

---

## 🛠️ Stack

```text
Python 3.10+ · PySide6 · OpenCV · mss · python-chess · Stockfish (UCI)
```

---

## ⚖️ Fair play

- **LIVE** = tracking only, no engine hints  
- **LIVE ENGINE** = only where rules allow it  
- No browser injection · no auto-moves · no server input  

Use engine help only in offline / vs-computer / explicitly allowed games.

---

## 🔧 Troubleshooting

| Issue | Fix |
|------|-----|
| Board stuck / wrong | **Reset**, new game from move 1, tighter region |
| Resync is inaccurate | Select only the 8×8 board; templates are learned from the starting position. Uncertain reads are rejected. Use **Edit Position** to drag pieces or right-click squares to correct a position, then set the side to move. |
| Missed a move | Wait for piece to settle · press **Analyze** |
| Stockfish not found | Place `.exe` in `stockfish\` and restart |
| Bad detection | Use **Classic** pieces on Chess.com |
| App freeze | Close in Task Manager · use latest build |

---

## 📁 Structure

```text
├── main.py
├── favicon.png / og.jpg / x-banner.jpg
├── src/          # UI, recognition, engine, chess logic
├── scripts/      # setup.bat · launch.bat
└── tests/
```

---

## 📄 License

**MIT** — see [LICENSE](LICENSE)  
Stockfish is **GPLv3** (separate license for the engine binary).

---

<p align="center">
  <b>Play smart. Play fair.</b><br/>
  <sub>ChessAI Overlay LIVE · Windows desktop companion</sub>
</p>
