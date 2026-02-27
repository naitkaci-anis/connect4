from __future__ import annotations

import os
import time
import json
from typing import Any, Dict, Optional, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import (
    ensure_config,
    Connect4,
    RED,
    YELLOW,
    EMPTY,
    COLOR_NAME,
    minimax_score_for_column,
    pick_best,
)

# ----------------
# DB (optionnelle)
# ----------------
DB_AVAILABLE = False
try:
    import db  # ton db.py
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False


app = FastAPI(title="Connect4 Web")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------
# Etat global (1 partie)
# ---------------------------
cfg = ensure_config()
game: Connect4 = Connect4(cfg["rows"], cfg["cols"], cfg["starting_color"])
game.mode = 2  # 0/1/2

robot_algo: str = "Random"   # "Random" ou "MiniMax"
robot_depth: int = 3

match_score = {RED: 0, YELLOW: 0}
_counted_games: Dict[int, str] = {}


def _update_match_score_if_needed():
    g = game
    if g.cursor <= 0:
        return
    if not g.finished:
        if g.game_index in _counted_games:
            prev = _counted_games.pop(g.game_index)
            if prev in (RED, YELLOW):
                match_score[prev] = max(0, match_score[prev] - 1)
        return
    if g.game_index in _counted_games:
        return
    if g.draw:
        _counted_games[g.game_index] = "D"
    else:
        _counted_games[g.game_index] = g.winner or ""
        if g.winner in (RED, YELLOW):
            match_score[g.winner] += 1


def _status_text() -> str:
    g = game
    mode_txt = ["0J", "1J", "2J"][g.mode]
    score_txt = f"Score: {COLOR_NAME[RED]} {match_score[RED]} - {match_score[YELLOW]} {COLOR_NAME[YELLOW]}"

    if g.finished:
        if g.draw:
            txt = f"[Partie #{g.game_index} | {mode_txt}] Fin : ÉGALITÉ."
        else:
            txt = f"[Partie #{g.game_index} | {mode_txt}] Fin : {COLOR_NAME[g.winner]} gagne !"
    else:
        turn = COLOR_NAME[g.current_turn]
        paused = " (PAUSE)" if g.paused else ""
        txt = f"[Partie #{g.game_index} | {mode_txt}] À jouer : {turn}{paused} | Robot: {robot_algo}"
        if robot_algo == "MiniMax":
            txt += f" (d={robot_depth})"

    txt += f" | coups: {g.cursor}/{len(g.moves)}"
    txt += " | " + score_txt
    return txt


def serialize_state() -> Dict[str, Any]:
    _update_match_score_if_needed()
    g = game
    return {
        "rows": g.rows,
        "cols": g.cols,
        "board": [row[:] for row in g.board],  # IMPORTANT: vrai tableau JSON
        "current_turn": g.current_turn,
        "finished": g.finished,
        "winner": g.winner,
        "draw": g.draw,
        "winning_line": g.winning_line,
        "cursor": g.cursor,
        "total": len(g.moves),
        "game_index": g.game_index,
        "mode": g.mode,
        "paused": g.paused,
        "robot_algo": robot_algo,
        "robot_depth": robot_depth,
        "match_score": {"R": match_score[RED], "Y": match_score[YELLOW]},
        "status_text": _status_text(),
    }


def _save_game_to_db_if_possible():
    if not DB_AVAILABLE:
        return

    g = game
    source = f"web_game_{g.game_index}"

    seq = ",".join(str(m.col + 1) for m in g.moves[: g.cursor])
    status = "FINISHED" if g.finished else "IN_PROGRESS"
    winner = g.winner if (g.finished and not g.draw) else None
    draw = bool(g.draw) if g.finished else False

    moves_payload = []
    for i, m in enumerate(g.moves[: g.cursor], start=1):
        moves_payload.append({"ply": i, "col": int(m.col), "row": int(m.row), "color": m.color})

    try:
        # adapte à ta signature db.py
        db.upsert_game_progress(
            source_filename=source,
            seq=seq,
            rows=g.rows,
            cols=g.cols,
            starting_color=g.starting_color,
            status=status,
            winner=winner,
            draw=draw,
            moves=moves_payload,
            confiance=1,
        )
    except Exception:
        # on évite de casser l'app web si DB KO
        pass


# ----------------
# Pydantic I/O
# ----------------
class SetIn(BaseModel):
    mode: Optional[int] = None
    robot_algo: Optional[str] = None
    robot_depth: Optional[int] = None


class MoveIn(BaseModel):
    col: int


class CursorIn(BaseModel):
    cursor: int


class LoadSnapIn(BaseModel):
    snapshot: Dict[str, Any]


class ConfigIn(BaseModel):
    rows: int
    cols: int
    starting_color: str
    cell_size: int
    margin: int
    drop_delay_ms: int


# ----------------
# Routes API
# ----------------
@app.get("/api/state")
def api_state():
    return serialize_state()


@app.post("/api/new")
def api_new():
    global game, cfg
    cfg = ensure_config()
    # nouvelle partie
    game = Connect4(cfg["rows"], cfg["cols"], cfg["starting_color"])
    _save_game_to_db_if_possible()
    return serialize_state()


@app.post("/api/pause")
def api_pause():
    game.paused = not game.paused
    return serialize_state()


@app.post("/api/set")
def api_set(payload: SetIn):
    global robot_algo, robot_depth

    if payload.mode is not None:
        if payload.mode not in (0, 1, 2):
            raise HTTPException(400, "mode must be 0,1,2")
        game.mode = payload.mode

    if payload.robot_algo is not None:
        ra = payload.robot_algo.lower()
        if ra in ("random", "rand"):
            robot_algo = "Random"
        elif ra in ("minimax", "mini"):
            robot_algo = "MiniMax"
        else:
            raise HTTPException(400, "robot_algo must be Random or MiniMax")

    if payload.robot_depth is not None:
        robot_depth = max(1, min(int(payload.robot_depth), 8))

    return serialize_state()


@app.post("/api/move")
def api_move(payload: MoveIn):
    col = int(payload.col)

    ok = game.drop_in_column(col)
    if not ok:
        raise HTTPException(400, "invalid move")

    _save_game_to_db_if_possible()
    return serialize_state()


@app.post("/api/undo")
def api_undo():
    game.undo()
    _save_game_to_db_if_possible()
    return serialize_state()


@app.post("/api/redo")
def api_redo():
    game.redo()
    _save_game_to_db_if_possible()
    return serialize_state()


@app.post("/api/cursor")
def api_cursor(payload: CursorIn):
    game.apply_to_cursor(int(payload.cursor))
    _save_game_to_db_if_possible()
    return serialize_state()


@app.post("/api/step_ai")
def api_step_ai():
    if not game.can_play() or game.finished:
        return serialize_state()

    # mode 1 : Rouge = humain
    if game.mode == 1 and game.current_turn == RED:
        raise HTTPException(400, "human turn (mode 1, RED)")

    valid = game.valid_columns()
    if not valid:
        return serialize_state()

    if robot_algo == "Random":
        idx = int(time.time() * 1000) % len(valid)
        game.drop_in_column(valid[idx])
        _save_game_to_db_if_possible()
        return serialize_state()

    # MiniMax
    # MiniMax sur 9x9 peut être très lent si depth trop haut
    depth = max(1, min(int(robot_depth), 4))
    if game.rows * game.cols >= 81:   # 9x9
        depth = min(depth, 3)         # limite auto pour garder fluide
    scores: List[Optional[int]] = [None] * game.cols
    tmp = [row[:] for row in game.board]
    for c in range(game.cols):
        if tmp[0][c] != EMPTY:
            scores[c] = None
        else:
            scores[c] = minimax_score_for_column(tmp, c, depth, game.current_turn)

    best = pick_best(scores)
    game.drop_in_column(best)
    _save_game_to_db_if_possible()
    return serialize_state()


@app.get("/api/save")
def api_save():
    snap = game.to_snapshot()
    return json.loads(json.dumps(snap, default=lambda o: o.__dict__))


@app.post("/api/load")
def api_load(payload: LoadSnapIn):
    global game
    from core import GameSnapshot

    snap = GameSnapshot(**payload.snapshot)
    game = Connect4.from_snapshot(snap)
    _save_game_to_db_if_possible()
    return serialize_state()


@app.get("/api/config")
def api_get_config():
    return ensure_config()


@app.post("/api/config")
def api_set_config(payload: ConfigIn):
    global game
    cfg2 = {
        "rows": payload.rows,
        "cols": payload.cols,
        "starting_color": payload.starting_color,
        "cell_size": payload.cell_size,
        "margin": payload.margin,
        "drop_delay_ms": payload.drop_delay_ms,
    }
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(cfg2, f, indent=2, ensure_ascii=False)

    cfg_norm = ensure_config()
    game = Connect4(cfg_norm["rows"], cfg_norm["cols"], cfg_norm["starting_color"])
    _save_game_to_db_if_possible()
    return {"ok": True, "config": cfg_norm}


@app.get("/api/db/list")
def api_db_list(limit: int = 500):
    if not DB_AVAILABLE:
        raise HTTPException(400, "DB non disponible")

    inprog = db.list_in_progress(limit=limit)
    allg = db.list_games(limit=limit)

    seen = set()
    out = []
    for gg in inprog + allg:
        gid = int(gg["id"])
        if gid in seen:
            continue
        seen.add(gid)
        out.append(gg)

    return {"games": out}


@app.post("/api/db/load/{game_id}")
def api_db_load(game_id: int):
    global game  # ✅ doit être AVANT tout usage de game

    if not DB_AVAILABLE:
        raise HTTPException(400, "DB non disponible")

    data = db.get_game_for_app(int(game_id))

    current_mode = game.mode  # OK (global déjà déclaré)

    rows = int(data["rows"])
    cols = int(data["cols"])
    start = data["starting_color"]

    game = Connect4(rows, cols, start)
    game.mode = current_mode

    # reconstruire moves
    from core import Move
    import time as _t

    game.moves = []
    for mv in data["moves"]:
        game.moves.append(
            Move(col=int(mv["col"]), row=int(mv["row"]), color=mv["color"], timestamp=_t.time())
        )

    game.apply_to_cursor(len(game.moves))
    _save_game_to_db_if_possible()
    return serialize_state()


# ----------------
# Static front
# ----------------
WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")

import os

@app.get("/api/db/ping")
def api_db_ping():
    url = os.getenv("DATABASE_URL")
    return {
        "db_available": DB_AVAILABLE,
        "has_database_url": bool(url),
        "database_url_prefix": (url[:30] + "...") if url else None,
    }
    
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

