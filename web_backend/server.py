from __future__ import annotations

import os
import time
import json
import secrets
import threading
from typing import Any, Dict, Optional, List

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import (
    ensure_config,
    Connect4,
    Move,
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
    import db
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False

print("SERVER.PY LOADED")

app = FastAPI(title="Connect4 Web")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------
# Etat global local (1 partie)
# ---------------------------
cfg = ensure_config()
game: Connect4 = Connect4(cfg["rows"], cfg["cols"], cfg["starting_color"])
game.mode = 2  # 0/1/2

robot_algo: str = "Random"
robot_depth: int = 3

match_score = {RED: 0, YELLOW: 0}
_counted_games: Dict[int, str] = {}

# verrou anti appels IA simultanés
ai_step_lock = threading.Lock()

# ---------------------------
# Etat global online
# ---------------------------
ONLINE_MODE = 3
online_rooms: Dict[str, Dict[str, Any]] = {}
waiting_room_id: Optional[str] = None


# ============================================================
# LOCAL HELPERS
# ============================================================

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
        "board": [row[:] for row in g.board],
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
        "moves": [
            {"ply": i, "col": int(m.col), "row": int(m.row), "color": m.color}
            for i, m in enumerate(g.moves[: g.cursor], start=1)
        ],
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
        moves_payload.append({
            "ply": i,
            "col": int(m.col),
            "row": int(m.row),
            "color": m.color
        })

    try:
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
        pass


def _save_online_game_to_db_if_possible(room: Dict[str, Any]):
    if not DB_AVAILABLE:
        print("[ONLINE DB] DB unavailable")
        return

    try:
        g: Connect4 = room["game"]
        room_id = room["room_id"]

        source = f"online_room_{room_id}"
        seq = ",".join(str(m.col + 1) for m in g.moves[: g.cursor])
        status = "FINISHED" if g.finished else "IN_PROGRESS"
        winner = g.winner if (g.finished and not g.draw) else None
        draw = bool(g.draw) if g.finished else False

        moves_payload = []
        for i, m in enumerate(g.moves[: g.cursor], start=1):
            moves_payload.append({
                "ply": i,
                "col": int(m.col),
                "row": int(m.row),
                "color": m.color
            })

        print("[ONLINE DB] save start")
        print("[ONLINE DB] source =", source)
        print("[ONLINE DB] seq =", seq)
        print("[ONLINE DB] status =", status)
        print("[ONLINE DB] winner =", winner)
        print("[ONLINE DB] draw =", draw)
        print("[ONLINE DB] moves_count =", len(moves_payload))

        result = db.upsert_game_progress(
            source_filename=source,
            seq=seq,
            rows=g.rows,
            cols=g.cols,
            starting_color=g.starting_color,
            status=status,
            winner=winner,
            draw=draw,
            moves=moves_payload,
            confiance=2,
        )

        print("[ONLINE DB] result =", result)

    except Exception as e:
        print("[ONLINE DB SAVE ERROR]", repr(e))


# ============================================================
# ONLINE HELPERS
# ============================================================

def _new_online_room() -> Dict[str, Any]:
    cfg_now = ensure_config()
    room_id = secrets.token_urlsafe(8)
    g = Connect4(cfg_now["rows"], cfg_now["cols"], cfg_now["starting_color"])
    g.mode = ONLINE_MODE

    room = {
        "room_id": room_id,
        "game": g,
        "players": {RED: None, YELLOW: None},
        "token_to_color": {},
        "created_at": time.time(),
        "updated_at": time.time(),
        "status": "waiting",
        "match_score": {RED: 0, YELLOW: 0},
        "counted_games": {},
    }
    online_rooms[room_id] = room
    return room


def _get_room_or_404(room_id: str) -> Dict[str, Any]:
    room = online_rooms.get(room_id)
    if not room:
        raise HTTPException(404, "room introuvable")
    return room


def _get_online_color_or_403(room: Dict[str, Any], player_token: str) -> str:
    color = room["token_to_color"].get(player_token)
    if color not in (RED, YELLOW):
        raise HTTPException(403, "player_token invalide")
    return color


def _online_update_match_score_if_needed(room: Dict[str, Any]):
    g: Connect4 = room["game"]
    counted_games: Dict[int, str] = room["counted_games"]
    room_score = room["match_score"]

    if g.cursor <= 0:
        return
    if not g.finished:
        if g.game_index in counted_games:
            prev = counted_games.pop(g.game_index)
            if prev in (RED, YELLOW):
                room_score[prev] = max(0, room_score[prev] - 1)
        return
    if g.game_index in counted_games:
        return
    if g.draw:
        counted_games[g.game_index] = "D"
    else:
        counted_games[g.game_index] = g.winner or ""
        if g.winner in (RED, YELLOW):
            room_score[g.winner] += 1


def _online_status_text(room: Dict[str, Any], player_token: str) -> str:
    g: Connect4 = room["game"]
    players = room["players"]
    color = room["token_to_color"].get(player_token)
    score = room["match_score"]

    if players[RED] is None or players[YELLOW] is None:
        return f"[Online #{room['room_id']}] En attente d'un adversaire..."

    my_color = COLOR_NAME[color] if color in (RED, YELLOW) else "?"
    score_txt = f"Score: {COLOR_NAME[RED]} {score[RED]} - {score[YELLOW]} {COLOR_NAME[YELLOW]}"

    if g.finished:
        if g.draw:
            txt = f"[Online #{room['room_id']}] Fin : ÉGALITÉ."
        else:
            txt = f"[Online #{room['room_id']}] Fin : {COLOR_NAME[g.winner]} gagne !"
    else:
        turn = COLOR_NAME[g.current_turn]
        if g.current_turn == color:
            txt = f"[Online #{room['room_id']}] Tu es {my_color} • À toi de jouer"
        else:
            txt = f"[Online #{room['room_id']}] Tu es {my_color} • Tour de {turn}"

    txt += f" | coups: {g.cursor}/{len(g.moves)}"
    txt += " | " + score_txt
    return txt


def _serialize_online_state(room: Dict[str, Any], player_token: str) -> Dict[str, Any]:
    _online_update_match_score_if_needed(room)

    g: Connect4 = room["game"]
    color = room["token_to_color"].get(player_token)

    return {
        "rows": g.rows,
        "cols": g.cols,
        "board": [row[:] for row in g.board],
        "current_turn": g.current_turn,
        "finished": g.finished,
        "winner": g.winner,
        "draw": g.draw,
        "winning_line": g.winning_line,
        "cursor": g.cursor,
        "total": len(g.moves),
        "game_index": g.game_index,
        "mode": ONLINE_MODE,
        "paused": False,
        "robot_algo": "Online",
        "robot_depth": 0,
        "match_score": {
            "R": room["match_score"][RED],
            "Y": room["match_score"][YELLOW]
        },
        "status_text": _online_status_text(room, player_token),
        "moves": [
            {"ply": i, "col": int(m.col), "row": int(m.row), "color": m.color}
            for i, m in enumerate(g.moves[: g.cursor], start=1)
        ],
        "online": {
            "room_id": room["room_id"],
            "color": color,
            "waiting": room["status"] == "waiting",
        }
    }


# ============================================================
# Pydantic I/O
# ============================================================

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


class BgaTableIn(BaseModel):
    table_id: int


class OnlineJoinIn(BaseModel):
    pass


class OnlineMoveIn(BaseModel):
    room_id: str
    player_token: str
    col: int


# ============================================================
# Routes API classiques
# ============================================================

@app.get("/api/state")
def api_state():
    return serialize_state()


@app.post("/api/new")
def api_new():
    global game, cfg
    cfg = ensure_config()
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
    if not ai_step_lock.acquire(blocking=False):
        return serialize_state()

    try:
        if not game.can_play() or game.finished:
            return serialize_state()

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

        depth = max(1, min(int(robot_depth), 6))

        cells = game.rows * game.cols
        if cells >= 81:
            depth = min(depth, 3)
        elif cells >= 72:
            depth = min(depth, 4)
        elif cells >= 56:
            depth = min(depth, 5)

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

    finally:
        ai_step_lock.release()


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
    global game

    if not DB_AVAILABLE:
        raise HTTPException(400, "DB non disponible")

    data = db.get_game_for_app(int(game_id))

    current_mode = game.mode

    rows = int(data["rows"])
    cols = int(data["cols"])
    start = data["starting_color"]

    game = Connect4(rows, cols, start)
    game.mode = current_mode

    import time as _t

    game.moves = []
    for mv in data["moves"]:
        game.moves.append(
            Move(col=int(mv["col"]), row=int(mv["row"]), color=mv["color"], timestamp=_t.time())
        )

    game.apply_to_cursor(len(game.moves))
    _save_game_to_db_if_possible()
    return serialize_state()


@app.post("/api/bga/load_table")
def api_bga_load_table(payload: BgaTableIn):
    global game

    table_id = int(payload.table_id)
    if table_id <= 0:
        raise HTTPException(400, "table_id invalide")

    try:
        from .bga_single_table import load_bga_table
    except Exception:
        try:
            from bga_single_table import load_bga_table
        except Exception as e:
            raise HTTPException(500, f"Module BGA introuvable: {e}")

    try:
        data = load_bga_table(table_id)
    except Exception as e:
        raise HTTPException(400, f"Impossible de charger la table BGA {table_id}: {e}")

    rows = int(data["rows"])
    cols = int(data["cols"])
    starting_color = data.get("starting_color", "R")
    raw_moves = data.get("moves", [])

    if not raw_moves:
        raise HTTPException(400, "Aucun coup récupéré pour cette table")

    current_mode = game.mode

    game = Connect4(rows, cols, starting_color)
    game.mode = current_mode

    game.moves = []
    for i, mv in enumerate(raw_moves, start=1):
        col = int(mv["col"])
        ok = game.drop_in_column(col)
        if not ok:
            raise HTTPException(400, f"Coup invalide au ply {i} (col={col})")

    _save_game_to_db_if_possible()
    return serialize_state()


# ============================================================
# Routes API online
# ============================================================

@app.post("/api/online/join")
def api_online_join(payload: OnlineJoinIn):
    global waiting_room_id

    if waiting_room_id:
        room = online_rooms.get(waiting_room_id)
        if room and room["players"][YELLOW] is None:
            token = secrets.token_urlsafe(16)
            room["players"][YELLOW] = token
            room["token_to_color"][token] = YELLOW
            room["status"] = "playing"
            room["updated_at"] = time.time()

            _save_online_game_to_db_if_possible(room)

            joined_room_id = waiting_room_id
            waiting_room_id = None

            return {
                "room_id": joined_room_id,
                "player_token": token,
                "color": YELLOW,
                "waiting": False,
            }

    room = _new_online_room()
    token = secrets.token_urlsafe(16)
    room["players"][RED] = token
    room["token_to_color"][token] = RED
    room["status"] = "waiting"
    room["updated_at"] = time.time()

    waiting_room_id = room["room_id"]

    _save_online_game_to_db_if_possible(room)

    return {
        "room_id": room["room_id"],
        "player_token": token,
        "color": RED,
        "waiting": True,
    }


@app.get("/api/online/state")
def api_online_state(
    room_id: str = Query(...),
    player_token: str = Query(...)
):
    room = _get_room_or_404(room_id)
    _get_online_color_or_403(room, player_token)
    return _serialize_online_state(room, player_token)


@app.post("/api/online/move")
def api_online_move(payload: OnlineMoveIn):
    room = _get_room_or_404(payload.room_id)
    color = _get_online_color_or_403(room, payload.player_token)

    g: Connect4 = room["game"]

    if room["players"][RED] is None or room["players"][YELLOW] is None:
        raise HTTPException(400, "En attente d'un adversaire")

    if g.finished:
        return _serialize_online_state(room, payload.player_token)

    if g.current_turn != color:
        raise HTTPException(400, "Ce n'est pas ton tour")

    ok = g.drop_in_column(int(payload.col))
    if not ok:
        raise HTTPException(400, "invalid move")

    room["updated_at"] = time.time()
    if g.finished:
        room["status"] = "finished"
    else:
        room["status"] = "playing"

    _save_online_game_to_db_if_possible(room)

    return _serialize_online_state(room, payload.player_token)


@app.get("/api/db/ping")
def api_db_ping():
    url = os.getenv("DATABASE_URL")
    return {
        "db_available": DB_AVAILABLE,
        "has_database_url": bool(url),
        "database_url_prefix": (url[:30] + "...") if url else None,
    }


# ----------------
# Static front
# ----------------
WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
