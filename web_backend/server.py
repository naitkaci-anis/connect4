from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import json
import secrets
import threading
import types
from typing import Any, Dict, Optional, List, Tuple

from ai_engine import ai_choose_column_from_game

# ── Import NeuralAI ──
try:
    from neural_ai import ai_choose_column_neural
    NEURAL_AVAILABLE = True
    print("✅  NeuralAI disponible")
except Exception as e:
    NEURAL_AVAILABLE = False
    print(f"⚠️  NeuralAI non disponible : {e}")

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
    _is_win,
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

# ── Plateau fixe 9x9 ──
FIXED_ROWS: int = 9
FIXED_COLS: int = 9
# ──────────────────────

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
game: Connect4 = Connect4(FIXED_ROWS, FIXED_COLS, cfg["starting_color"])
game.mode = 2  # 0/1/2

robot_algo: str = "Random"
robot_algo_r: str = "Random"   # mode 0 : robot jouant Rouge
robot_algo_y: str = "MiniMax"  # mode 0 : robot jouant Jaune
robot_depth: int = 4
ai_starts: bool = False

match_score = {RED: 0, YELLOW: 0}
_counted_games: Dict[int, str] = {}

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
        if robot_algo in ("MiniMax", "Strategic"):
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
        "robot_algo_r": robot_algo_r,
        "robot_algo_y": robot_algo_y,
        "robot_depth": robot_depth,
        "ai_starts": ai_starts,
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
    if not g.finished:
        return

    source = f"web_game_{g.game_index}"
    seq = ",".join(str(m.col + 1) for m in g.moves[: g.cursor])
    status = "FINISHED"
    winner = g.winner if not g.draw else None
    draw = bool(g.draw)

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
            confiance=2,
        )
    except Exception:
        pass


# ============================================================
# ONLINE HELPERS
# ============================================================

def _new_online_room() -> Dict[str, Any]:
    cfg_now = ensure_config()
    room_id = secrets.token_urlsafe(8)
    g = Connect4(FIXED_ROWS, FIXED_COLS, cfg_now["starting_color"])
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
# PAINT HELPERS
# ============================================================

def _validate_painted_board(board_in: List[List[str]], rows_n: int, cols_n: int):
    if rows_n <= 0 or cols_n <= 0:
        raise HTTPException(400, "Grille vide")

    for r in range(rows_n):
        if len(board_in[r]) != cols_n:
            raise HTTPException(400, "Grille non rectangulaire")

    for r in range(rows_n):
        for c in range(cols_n):
            if board_in[r][c] not in (RED, YELLOW, EMPTY):
                raise HTTPException(400, f"Cellule ({r},{c}) invalide : {board_in[r][c]}")

    for c in range(cols_n):
        seen_empty_below = False
        for r in range(rows_n - 1, -1, -1):
            cell = board_in[r][c]
            if cell == EMPTY:
                seen_empty_below = True
            else:
                if seen_empty_below:
                    raise HTTPException(400, f"Grille invalide : pion flottant en colonne {c + 1}")


def _infer_turn_from_board(board_in: List[List[str]], starting_color: str = RED) -> str:
    r_count = sum(1 for row in board_in for cell in row if cell == RED)
    y_count = sum(1 for row in board_in for cell in row if cell == YELLOW)

    if starting_color == RED:
        if r_count == y_count:
            return RED
        if r_count == y_count + 1:
            return YELLOW
    else:
        if r_count == y_count:
            return YELLOW
        if y_count == r_count + 1:
            return RED

    raise HTTPException(
        400,
        f"Nombre de pions incohérent (R={r_count}, Y={y_count}) pour starting_color={starting_color}"
    )


def _detect_winner_on_board(board_in: List[List[str]]) -> Tuple[Optional[str], bool]:
    rows_n = len(board_in)
    cols_n = len(board_in[0]) if board_in else 0

    def has4(color: str) -> bool:
        for r in range(rows_n):
            for c in range(cols_n):
                if board_in[r][c] != color:
                    continue
                if c + 3 < cols_n and all(board_in[r][c + k] == color for k in range(4)):
                    return True
                if r + 3 < rows_n and all(board_in[r + k][c] == color for k in range(4)):
                    return True
                if r + 3 < rows_n and c + 3 < cols_n and all(board_in[r + k][c + k] == color for k in range(4)):
                    return True
                if r + 3 < rows_n and c - 3 >= 0 and all(board_in[r + k][c - k] == color for k in range(4)):
                    return True
        return False

    red_win = has4(RED)
    yellow_win = has4(YELLOW)

    if red_win and yellow_win:
        raise HTTPException(400, "Grille invalide : Rouge et Jaune gagnent simultanément")
    if red_win:
        return RED, False
    if yellow_win:
        return YELLOW, False

    is_full = all(board_in[r][c] != EMPTY for r in range(rows_n) for c in range(cols_n))
    if is_full:
        return None, True

    return None, False


# ============================================================
# Pydantic I/O
# ============================================================

class SetIn(BaseModel):
    mode: Optional[int] = None
    robot_algo: Optional[str] = None
    robot_algo_r: Optional[str] = None
    robot_algo_y: Optional[str] = None
    robot_depth: Optional[int] = None
    ai_starts: Optional[bool] = None


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


class LoadSequenceIn(BaseModel):
    sequence: str
    rows: Optional[int] = None
    cols: Optional[int] = None
    starting_color: Optional[str] = "R"
    source: Optional[str] = None


class OnlineJoinIn(BaseModel):
    pass


class OnlineMoveIn(BaseModel):
    room_id: str
    player_token: str
    col: int


class PaintBoardIn(BaseModel):
    board: List[List[str]]


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
    current_mode = game.mode
    game = Connect4(FIXED_ROWS, FIXED_COLS, cfg["starting_color"])
    game.mode = current_mode
    _save_game_to_db_if_possible()
    return serialize_state()


@app.post("/api/pause")
def api_pause():
    game.paused = not game.paused
    return serialize_state()


@app.post("/api/set")
def api_set(payload: SetIn):
    global robot_algo, robot_algo_r, robot_algo_y, robot_depth, ai_starts

    if payload.mode is not None:
        if payload.mode not in (0, 1, 2):
            raise HTTPException(400, "mode must be 0,1,2")
        game.mode = payload.mode

    def _parse_algo(ra: str) -> str:
        ra = ra.lower()
        if ra in ("random", "rand"):                      return "Random"
        if ra in ("minimax", "mini"):                     return "MiniMax"
        if ra in ("strategic", "strat"):                  return "Strategic"
        if ra in ("neural", "neuralai", "ia", "reseau"):  return "Neural"
        raise HTTPException(400, f"robot_algo inconnu : {ra}")

    if payload.robot_algo is not None:
        robot_algo = _parse_algo(payload.robot_algo)
    if payload.robot_algo_r is not None:
        robot_algo_r = _parse_algo(payload.robot_algo_r)
    if payload.robot_algo_y is not None:
        robot_algo_y = _parse_algo(payload.robot_algo_y)

    if payload.robot_depth is not None:
        robot_depth = max(1, min(int(payload.robot_depth), 8))
    if payload.ai_starts is not None:
        ai_starts = bool(payload.ai_starts)

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
    if game.cursor > 0:
        game.undo()
    _save_game_to_db_if_possible()
    return serialize_state()


@app.post("/api/redo")
def api_redo():
    if game.cursor < len(game.moves):
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

        if game.mode == 1:
            if not ai_starts and game.current_turn == RED:
                raise HTTPException(400, "human turn")
            if ai_starts and game.current_turn == YELLOW:
                raise HTTPException(400, "human turn")

        valid = game.valid_columns()
        if not valid:
            return serialize_state()

        # En mode IA vs IA, choisir l'algo selon la couleur qui joue
        if game.mode == 0:
            algo = robot_algo_r if game.current_turn == RED else robot_algo_y
        else:
            algo = robot_algo

        if algo == "Random":
            idx = int(time.time() * 1000) % len(valid)
            game.drop_in_column(valid[idx])
        elif algo == "Neural" and NEURAL_AVAILABLE:
            best_col = ai_choose_column_neural(game)
            game.drop_in_column(best_col)
        elif algo == "Neural" and not NEURAL_AVAILABLE:
            best_col = ai_choose_column_from_game(game, DB_AVAILABLE, robot_depth, mode="minimax")
            game.drop_in_column(best_col)
        else:
            mode_str = "strategic" if algo == "Strategic" else "minimax"
            best_col = ai_choose_column_from_game(game, DB_AVAILABLE, robot_depth, mode=mode_str)
            game.drop_in_column(best_col)

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
        "rows": FIXED_ROWS,
        "cols": FIXED_COLS,
        "starting_color": payload.starting_color,
        "cell_size": payload.cell_size,
        "margin": payload.margin,
        "drop_delay_ms": payload.drop_delay_ms,
    }
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(cfg2, f, indent=2, ensure_ascii=False)

    cfg_norm = ensure_config()
    game = Connect4(FIXED_ROWS, FIXED_COLS, cfg_norm["starting_color"])
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
    start = data["starting_color"]
    # Plateau fixe 9x9 — on ignore les rows/cols de la DB
    game = Connect4(FIXED_ROWS, FIXED_COLS, start)
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

    starting_color = data.get("starting_color", "R")
    raw_moves = data.get("moves", [])

    if not raw_moves:
        raise HTTPException(400, "Aucun coup récupéré pour cette table")

    current_mode = game.mode
    # Plateau fixe 9x9 — on ignore les rows/cols BGA
    game = Connect4(FIXED_ROWS, FIXED_COLS, starting_color)
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
# Chargement depuis fichier / séquence locale
# ============================================================

@app.post("/api/load_sequence")
def api_load_sequence(payload: LoadSequenceIn):
    """
    Charge une partie depuis une séquence de colonnes 1-indexées (chiffres 1-9).
    La séquence vient du nom du fichier .txt (ex: "31313.txt" → séquence "31313").
    rows/cols optionnels : fallback sur config.json.
    """
    global game

    raw = payload.sequence.strip().replace(";", "").replace(",", "").replace(" ", "")
    if not raw:
        raise HTTPException(400, "Séquence vide")

    # Vérification : uniquement des chiffres 1-9
    for ch in raw:
        if ch not in "123456789":
            raise HTTPException(400, f"Caractère invalide dans la séquence : '{ch}' (seuls 1-9 sont acceptés)")

    # Conversion en liste d'entiers 0-indexés
    try:
        cols_seq = [int(ch) - 1 for ch in raw]   # "31313" → [2, 0, 2, 0, 2]
    except ValueError as e:
        raise HTTPException(400, f"Séquence invalide : {e}")

    rows_n = FIXED_ROWS
    cols_n = FIXED_COLS
    start_color = (payload.starting_color or "R").upper()
    if start_color not in ("R", "Y"):
        start_color = "R"

    # Vérification que les colonnes sont dans les limites du plateau
    for i, col in enumerate(cols_seq, start=1):
        if col < 0 or col >= cols_n:
            raise HTTPException(
                400,
                f"Coup {i} : colonne {col + 1} hors limites (plateau {cols_n} colonnes). "
                "Vérifiez la taille du plateau dans Paramètres."
            )

    current_mode = game.mode
    game = Connect4(rows_n, cols_n, start_color)
    game.mode = current_mode

    for i, col in enumerate(cols_seq, start=1):
        ok = game.drop_in_column(col)
        if not ok:
            raise HTTPException(
                400,
                f"Coup invalide au ply {i} (col={col + 1}) — colonne pleine ou partie déjà terminée"
            )

    _save_game_to_db_if_possible()
    return serialize_state()


# ============================================================
# Hint — meilleur coup pour l'humain (MiniMax)
# ============================================================

@app.get("/api/hint")
def api_hint():
    """
    Retourne le meilleur coup calculé par MiniMax pour le joueur courant.
    Utilisé pour afficher une aide au joueur humain.
    """
    g = game

    if g.finished:
        return {"best_col": None, "scores": [], "current_turn": None,
                "min_score": 0, "max_score": 0}

    depth = min(robot_depth, 3)   
    tmp = [row[:] for row in g.board]
    scores: List[Optional[int]] = []

    for c in range(g.cols):
        sc = minimax_score_for_column(tmp, c, depth, g.current_turn)
        scores.append(sc)

    try:
        best_col = pick_best(scores)
    except Exception:
        best_col = None

    valid = [s for s in scores if s is not None]
    min_s = min(valid) if valid else 0
    max_s = max(valid) if valid else 0

    return {
        "best_col": best_col,
        "scores": scores,
        "current_turn": g.current_turn,
        "min_score": min_s,
        "max_score": max_s,
    }


# ============================================================
# Neural Eval — prédiction par le réseau neuronal
# ============================================================

@app.get("/api/neural_eval")
def api_neural_eval():
    """Évaluation rapide par la tête value du réseau neuronal."""
    g = game

    if g.finished:
        if g.draw:
            return {"label": "nul", "value": 0.0, "confidence": 100,
                    "color_wins": None, "explanation": "Partie terminée : égalité."}
        return {"label": "victoire", "value": 1.0 if g.winner == RED else -1.0,
                "confidence": 100, "color_wins": g.winner,
                "explanation": f"Partie terminée : {COLOR_NAME[g.winner]} a gagné."}

    if not NEURAL_AVAILABLE:
        return {"label": "unavailable", "value": 0.0, "confidence": 0,
                "color_wins": None, "explanation": "Modèle neural non disponible."}

    try:
        import torch
        from neural_ai import NeuralAI
        ai_inst = NeuralAI.get_instance()
        if ai_inst is None:
            return {"label": "unavailable", "value": 0.0, "confidence": 0,
                    "color_wins": None, "explanation": "connect4_model.pt introuvable."}

        turn = g.current_turn
        tensor = ai_inst._board_to_tensor(g.board, turn)
        with torch.no_grad():
            _, val_t = ai_inst.model(tensor.to(ai_inst.device))
        v = float(val_t.item())           # -1..+1 du point de vue du joueur courant
        v_red = v if turn == RED else -v  # ramené en perspective Rouge

        conf = int(abs(v) * 100)
        opp = YELLOW if turn == RED else RED

        if v > 0.45:
            label, color_wins = "victoire", turn
            expl = f"L'IA prédit une victoire de {COLOR_NAME[turn]}. (confiance {conf}%)"
        elif v < -0.45:
            label, color_wins = "defaite", opp
            expl = f"L'IA prédit une victoire de {COLOR_NAME[opp]}. (confiance {conf}%)"
        elif abs(v) < 0.15:
            label, color_wins = "nul", None
            expl = f"L'IA prédit un match nul. (confiance {conf}%)"
        else:
            label, color_wins = "incertain", None
            expl = f"Position incertaine. (valeur {v:+.2f})"

        return {"label": label, "value": round(v_red, 3),
                "confidence": conf, "color_wins": color_wins,
                "current_turn": turn, "explanation": expl}

    except Exception as e:
        return {"label": "error", "value": 0.0, "confidence": 0,
                "color_wins": None, "explanation": str(e)}


# ============================================================
# Prédiction IA — minimax symétrique + détection de forks
# ============================================================
#
# Les deux joueurs jouent à la même profondeur (robot_depth).
# Qui a l'avantage positionnel (double menace, fork) gagne
# même à profondeur égale — comme en vrai jeu.
#
# Niveaux de certitude :
#  1. Victoire immédiate (1 coup)
#  2. Double menace adversaire (défaite forcée en 2 coups)
#  3. Fork disponible pour joueur courant (win en 3 coups)
#  4. Suite prouvée par minimax iteratif jusqu'à robot_depth
#  5. Avantage heuristique (score positionnel + neural)
#
# Réponse JSON :
#   winner       : "R" | "Y" | "draw" | "unknown"
#   moves_left   : int ≥ 1 si prouvé/estimé, -1 si inconnu
#   certain      : bool  (True = victoire mathématiquement prouvée)
#   threat       : "fork" | "double" | "single" | null
#   best_col     : colonne recommandée (0-indexé)
#   score_pct    : 0-100 côté Rouge
#   reached_depth: profondeur réellement atteinte
#   explanation  : texte humain (une seule phrase claire)
# ============================================================

import math as _math

_PRED_WIN     = 100_000   # score terminal dans _pmm
_PRED_BUDGET  = 4.0       # secondes max
_PRED_MAXD    = 10        # profondeur max absolue
_pmm_deadline = 0.0       # mis à jour avant chaque appel


def _pdrop(board, col, color):
    rows = len(board)
    if board[0][col] != EMPTY:
        return None
    r = rows - 1
    while r >= 0 and board[r][col] != EMPTY:
        r -= 1
    if r < 0:
        return None
    board[r][col] = color
    return r


def _pheur(board, ai):
    """
    Heuristique positionnelle améliorée.
    Poids élevés pour les menaces ouvertes (3-en-ligne avec 2 extrémités libres)
    et les forks potentiels (2 menaces croisées).
    """
    rows, cols = len(board), len(board[0])
    opp    = YELLOW if ai == RED else RED
    center = cols // 2
    s = 0

    # Bonus de centralité
    for c in range(cols):
        w = (cols - abs(c - center)) * 2
        for r in range(rows):
            if   board[r][c] == ai:  s += w
            elif board[r][c] == opp: s -= w

    def sw(win):
        a, o, e = win.count(ai), win.count(opp), win.count(EMPTY)
        if o == 0:  # fenêtre pure ai
            if a == 4:              return  50_000   # victoire (ne devrait pas arriver ici)
            if a == 3 and e == 1:   return  10_000   # menace directe
            if a == 2 and e == 2:   return    400
            if a == 1 and e == 3:   return     50
        if a == 0:  # fenêtre pure opp
            if o == 4:              return -50_000
            if o == 3 and e == 1:   return -15_000   # menace adversaire plus dangereuse
            if o == 2 and e == 2:   return   -600
            if o == 1 and e == 3:   return    -80
        return 0

    directions = []
    # Horizontal
    for r in range(rows):
        for c in range(cols - 3):
            directions.append([board[r][c+i] for i in range(4)])
    # Vertical
    for c in range(cols):
        for r in range(rows - 3):
            directions.append([board[r+i][c] for i in range(4)])
    # Diag /
    for r in range(3, rows):
        for c in range(cols - 3):
            directions.append([board[r-i][c+i] for i in range(4)])
    # Diag \
    for r in range(rows - 3):
        for c in range(cols - 3):
            directions.append([board[r+i][c+i] for i in range(4)])

    for win in directions:
        s += sw(win)

    return s


def _count_forks(board, color):
    """
    Retourne (nb_fork_cols, fork_cols) :
    cols où `color` peut jouer et créer ≥ 2 menaces immédiates simultanées
    (fork = victoire forcée en 3 coups max).
    """
    cols   = len(board[0])
    result = []
    for c in range(cols):
        r = _pdrop(board, c, color)
        if r is None:
            continue
        n_threats, _ = _count_wins(board, color)
        board[r][c] = EMPTY
        if n_threats >= 2:
            result.append(c)
    return len(result), result


def _pmm(board, depth, alpha, beta, maximizing, ai):
    """
    Minimax alpha-beta dédié à la prédiction.

    Convention score terminal : ±(_PRED_WIN + depth_restant)
    Plus depth_restant est élevé = victoire plus tôt = plus favorable.

    Conséquence directe :
      - AI maximise → choisit la victoire la PLUS RAPIDE (depth_restant max)
      - Minimizing  → choisit la défaite la PLUS LENTE (depth_restant min pour opp)
    Donc moves_left = depth_racine - depth_restant  ← distance RÉELLE.
    """
    global _pmm_deadline
    opp = YELLOW if ai == RED else RED

    if _is_win(board, ai):  return _PRED_WIN + depth    # ai gagne ici
    if _is_win(board, opp): return -(_PRED_WIN + depth) # opp gagne ici

    cols  = len(board[0])
    valid = [c for c in range(cols) if board[0][c] == EMPTY]

    if depth == 0 or not valid:
        return _pheur(board, ai)

    if time.time() > _pmm_deadline:
        return _pheur(board, ai)

    center = cols // 2
    valid.sort(key=lambda c: abs(c - center))

    if maximizing:
        v = -_math.inf
        for c in valid:
            r = _pdrop(board, c, ai)
            if r is None: continue
            v = max(v, _pmm(board, depth-1, alpha, beta, False, ai))
            board[r][c] = EMPTY
            alpha = max(alpha, v)
            if alpha >= beta: break
        return int(v)
    else:
        v = _math.inf
        for c in valid:
            r = _pdrop(board, c, opp)
            if r is None: continue
            v = min(v, _pmm(board, depth-1, alpha, beta, True, ai))
            board[r][c] = EMPTY
            beta = min(beta, v)
            if alpha >= beta: break
        return int(v)


def _count_wins(board, color):
    """Retourne le nombre de colonnes où color gagne immédiatement."""
    cols = len(board[0])
    count = 0
    wins  = []
    for c in range(cols):
        r = _pdrop(board, c, color)
        if r is None: continue
        if _is_win(board, color):
            count += 1
            wins.append(c)
        board[r][c] = EMPTY
    return count, wins


@app.get("/api/predict")
def api_predict():
    """
    Prédiction IA — minimax pur à profondeur choisie par l'utilisateur.

    Indépendant du robot et de son algorithme : utilise TOUJOURS minimax.
    La profondeur est passée en paramètre par le frontend.

    Niveaux de certitude (du plus au moins certain) :
      1. Victoire immédiate (1 coup)
      2. Double menace adversaire — défaite forcée en 2 coups
      3. Fork disponible — victoire forcée en 3 coups
      4. Suite prouvée par minimax (profondeur demandée)
      5. Avantage heuristique fort  → estimation moves_left
      6. Réseau neuronal (si disponible)
      7. Équilibré / inconnu
    """
    global _pmm_deadline
    g   = game
    # Profondeur choisie par l'utilisateur, indépendante du robot
    use_depth = 8  # profondeur fixe

    # ── 0. Partie déjà terminée ──────────────────────────────────
    if g.finished:
        if g.draw:
            return {"winner": "draw", "moves_left": 0, "certain": True,
                    "threat": None, "best_col": None, "score_pct": 50,
                    "reached_depth": 0,
                    "current_move": current_move,
                    "explanation": "Partie terminée : égalité."}
        sp = 92 if g.winner == RED else 8
        return {"winner": g.winner, "moves_left": 0, "certain": True,
                "threat": None, "best_col": None, "score_pct": sp,
                "reached_depth": 0,
                "current_move": current_move,
                "explanation": f"Partie terminée : {COLOR_NAME[g.winner]} a gagné."}

    player       = g.current_turn
    opp          = YELLOW if player == RED else RED
    board        = [row[:] for row in g.board]
    current_move = g.cursor + 1   # numéro du prochain coup (1-indexé)
    cols   = g.cols
    center = cols // 2

    valid = sorted(
        [c for c in range(cols) if board[0][c] == EMPTY],
        key=lambda c: abs(c - center)
    )

    def _sp(w: str, intensity: float) -> int:
        intensity = max(0.0, min(1.0, intensity))
        if w == RED:    return int(50 + intensity * 42)
        if w == YELLOW: return int(50 - intensity * 42)
        return 50

    # Label du joueur courant pour les explications
    turn_label = COLOR_NAME[player]   # "Rouge" ou "Jaune"
    opp_label  = COLOR_NAME[opp]

    # ── 1. Victoire immédiate joueur courant ─────────────────────
    n_wins_p, win_cols_p = _count_wins(board, player)
    if n_wins_p >= 1:
        best = win_cols_p[0]
        sp   = _sp(player, 1.0)
        return {"winner": player, "moves_left": 1, "certain": True,
                "threat": "single", "best_col": best, "score_pct": sp,
                "reached_depth": 1,
                "current_move": current_move,
                "explanation": f"C'est au {turn_label} de jouer. Victoire immédiate en jouant col {best+1}."}

    # ── 2. Double menace adversaire (défaite forcée en 2 coups) ──
    n_wins_o, win_cols_o = _count_wins(board, opp)
    if n_wins_o >= 2:
        sp = _sp(opp, 1.0)
        return {"winner": opp, "moves_left": 2, "certain": True,
                "threat": "double", "best_col": win_cols_o[0], "score_pct": sp,
                "reached_depth": 2,
                "current_move": current_move,
                "explanation": (f"C'est au {turn_label} de jouer. "
                                f"{opp_label} a {n_wins_o} menaces simultanées — "
                                f"défaite forcée en 2 coups.")}

    # ── 3. Fork disponible pour le joueur courant (win en 3 coups)
    n_fork_p, fork_cols_p = _count_forks(board, player)
    if n_fork_p >= 1:
        best = fork_cols_p[0]
        sp   = _sp(player, 0.95)
        return {"winner": player, "moves_left": 3, "certain": True,
                "threat": "fork", "best_col": best, "score_pct": sp,
                "reached_depth": 3,
                "current_move": current_move,
                "explanation": (f"C'est au {turn_label} de jouer. "
                                f"Fork col {best+1} : 2 menaces simultanées — victoire forcée en 3 coups.")}

    # ── 4. Minimax iteratif jusqu'à use_depth ────────────────────
    _pmm_deadline = time.time() + _PRED_BUDGET

    proven_winner = None
    proven_ml     = -1
    proven_col    = -1
    best_heur_score = 0
    best_heur_col   = valid[0] if valid else 0
    reached_depth   = 0

    for depth in range(1, use_depth + 1):
        if time.time() > _pmm_deadline:
            break

        depth_best_score = -_math.inf
        depth_best_col   = valid[0]
        timed_out        = False

        for c in valid:
            if time.time() > _pmm_deadline:
                timed_out = True
                break
            r = _pdrop(board, c, player)
            if r is None:
                continue
            sc = _pmm(board, depth - 1, -_math.inf, _math.inf, False, player)
            board[r][c] = EMPTY
            if sc > depth_best_score:
                depth_best_score = sc
                depth_best_col   = c

        if timed_out and depth > 1:
            break

        reached_depth   = depth
        best_heur_score = depth_best_score
        best_heur_col   = depth_best_col

        # Victoire forcée prouvée pour le joueur courant
        if depth_best_score >= _PRED_WIN:
            remaining = depth_best_score - _PRED_WIN
            ml = max(1, depth - remaining)
            proven_winner = player
            proven_ml     = ml
            proven_col    = depth_best_col
            break

        # Défaite forcée prouvée (toutes les colonnes perdent)
        if depth_best_score <= -_PRED_WIN:
            remaining = (-depth_best_score) - _PRED_WIN
            ml = max(1, depth - remaining)
            proven_winner = opp
            proven_ml     = ml
            proven_col    = depth_best_col
            break

    # ── 5. Victoire forcée prouvée ───────────────────────────────
    if proven_winner is not None:
        ml    = proven_ml
        turns = max(1, (ml + 1) // 2)
        sp    = _sp(proven_winner, 1.0)
        name  = COLOR_NAME[proven_winner]
        # Qui joue en premier dans cette suite ?
        first = turn_label if proven_winner == player else opp_label
        return {"winner": proven_winner, "moves_left": ml, "certain": True,
                "threat": None, "best_col": proven_col, "score_pct": sp,
                "reached_depth": reached_depth,
                "current_move": current_move,
                "explanation": (f"C'est au {turn_label} de jouer. "
                                f"{name} gagne en {ml} coup(s) — suite prouvée (prof. {reached_depth}), col {proven_col+1}.")}

    # ── 6. Avantage heuristique fort → estimation ─────────────────
    # IMPORTANT : le score minimax tient DÉJÀ compte des blocages futurs
    # car les deux joueurs jouent optimalement à profondeur use_depth.
    # Un avantage heuristique = même après avoir joué les meilleurs coups
    # des deux côtés, une couleur reste structurellement supérieure.
    #
    # Seuil relevé pour éviter les faux positifs du type "Rouge a 3 en ligne
    # mais Jaune joue prochain et va bloquer" → à depth ≥ 4, le minimax
    # voit le blocage et le score s'équilibre. Si le score reste élevé
    # malgré le blocage, c'est un vrai avantage.
    SEUIL_CLAIR    = 20_000   # faux positifs éliminés sous ce seuil
    SEUIL_DECISIF  = 60_000

    # Note de blocage : si l'adversaire a 1 menace, le joueur peut bloquer
    # → on le mentionne dans l'explication pour éviter la confusion
    if n_wins_o == 1:
        block_note = (f"C'est au {turn_label} de jouer — "
                      f"il peut bloquer la menace de {opp_label}. ")
        threat_tag = "single"
    else:
        block_note = f"C'est au {turn_label} de jouer. "
        threat_tag = None

    if abs(best_heur_score) > SEUIL_CLAIR:
        adv_color = player if best_heur_score > 0 else opp
        adv_name  = COLOR_NAME[adv_color]
        intensity = min(1.0, abs(best_heur_score) / SEUIL_DECISIF)
        sp        = _sp(adv_color, intensity)

        # Estimation moves_left
        if abs(best_heur_score) > SEUIL_DECISIF:
            est_ml = reached_depth + 1
        else:
            ratio  = (abs(best_heur_score) - SEUIL_CLAIR) / (SEUIL_DECISIF - SEUIL_CLAIR)
            est_ml = int(reached_depth * 2 * (1 - ratio) + (reached_depth + 2) * ratio)
            est_ml = max(reached_depth + 1, est_ml)

        est_turns = max(1, (est_ml + 1) // 2)

        return {"winner": adv_color, "moves_left": est_ml, "certain": False,
                "threat": threat_tag, "best_col": best_heur_col, "score_pct": sp,
                "reached_depth": reached_depth,
                "current_move": current_move,
                "explanation": (f"{block_note}"
                                f"{adv_name} en avantage (prof. {reached_depth}) — "
                                f"victoire estimée ~{est_ml} coup(s) ({est_turns} tour(s)).")}

    # ── 7. Réseau neuronal (fallback) ────────────────────────────
    neural_winner = None
    neural_conf   = 0
    neural_v_red  = 0.0

    if NEURAL_AVAILABLE:
        try:
            import torch
            from neural_ai import NeuralAI
            inst = NeuralAI.get_instance()
            if inst is not None:
                turn_nn = g.current_turn
                tensor  = inst._board_to_tensor(g.board, turn_nn)
                with torch.no_grad():
                    _, val_t = inst.model(tensor.to(inst.device))
                v     = float(val_t.item())
                v_red = v if turn_nn == RED else -v
                conf  = int(abs(v) * 100)
                neural_conf  = conf
                neural_v_red = v_red
                if v > 0.4:
                    neural_winner = turn_nn
                elif v < -0.4:
                    neural_winner = (YELLOW if turn_nn == RED else RED)
                elif abs(v) < 0.15:
                    neural_winner = "draw"
        except Exception:
            pass

    if neural_winner and neural_winner not in ("draw", "unknown") and neural_conf > 40:
        w         = neural_winner
        w_name    = COLOR_NAME[w]
        sp        = _sp(w, neural_conf / 100.0)
        est_ml    = max(reached_depth + 2, int((1.0 - neural_conf / 100.0) * 20) + 4)
        est_turns = max(1, (est_ml + 1) // 2)
        return {"winner": w, "moves_left": est_ml, "certain": False,
                "threat": threat_tag, "best_col": best_heur_col, "score_pct": sp,
                "reached_depth": reached_depth,
                "current_move": current_move,
                "explanation": (f"{block_note}"
                                f"{w_name} en avantage (réseau {neural_conf}%) — "
                                f"victoire estimée ~{est_ml} coup(s) ({est_turns} tour(s)).")}

    if neural_winner == "draw" and neural_conf > 40:
        return {"winner": "draw", "moves_left": -1, "certain": False,
                "threat": threat_tag, "best_col": best_heur_col, "score_pct": 50,
                "reached_depth": reached_depth,
                "current_move": current_move,
                "explanation": f"{block_note}Position équilibrée (prof. {reached_depth})."}

    # ── 8. Aucun avantage détecté ─────────────────────────────────
    return {"winner": "unknown", "moves_left": -1, "certain": False,
            "threat": threat_tag, "best_col": best_heur_col, "score_pct": 50,
            "reached_depth": reached_depth,
            "current_move": current_move,
            "explanation": f"{block_note}Position équilibrée (prof. {reached_depth}) — aucun avantage décisif."}



# ============================================================
# Paint & reprise
# ============================================================

@app.post("/api/paint")
def api_paint(payload: PaintBoardIn):
    global game

    board_in = payload.board
    rows_n = len(board_in)
    cols_n = len(board_in[0]) if board_in else 0

    if rows_n != game.rows or cols_n != game.cols:
        raise HTTPException(
            400,
            f"Grille {rows_n}x{cols_n} incompatible avec config {game.rows}x{game.cols}"
        )

    _validate_painted_board(board_in, rows_n, cols_n)
    inferred_turn = _infer_turn_from_board(board_in, game.starting_color)
    winner, draw = _detect_winner_on_board(board_in)

    new_game = Connect4(FIXED_ROWS, FIXED_COLS, game.starting_color)
    new_game.mode = game.mode
    new_game.board = [row[:] for row in board_in]
    new_game.current_turn = inferred_turn
    new_game.paused = False
    new_game.moves = []
    new_game.cursor = 0
    new_game.finished = winner is not None or draw
    new_game.winner = winner
    new_game.draw = draw
    new_game.winning_line = None

    # ── Patch apply_to_cursor pour que undo/redo parte du plateau peint
    # et non d'un plateau vide. On capture la snapshot dans la closure.
    _base = [row[:] for row in board_in]
    _base_turn = inferred_turn

    def _patched_apply(self, cursor: int):
        cursor = max(0, min(cursor, len(self.moves)))
        # Toujours repartir du plateau peint (pas d'un plateau vide)
        self.board = [row[:] for row in _base]
        self.finished = False
        self.draw = False
        self.winner = None
        self.winning_line = None
        self.cursor = 0
        self.current_turn = _base_turn
        for i in range(cursor):
            mv = self.moves[i]
            self.board[mv.row][mv.col] = mv.color
            self.cursor += 1
            self._update_after_move(mv.row, mv.col, mv.color)
            if self.finished:
                break
            self.current_turn = YELLOW if self.current_turn == RED else RED

    new_game.apply_to_cursor = types.MethodType(_patched_apply, new_game)

    game = new_game
    _save_game_to_db_if_possible()

    data = serialize_state()
    data["paint_analysis"] = {
        "current_turn_inferred": inferred_turn,
        "red_name": COLOR_NAME[RED],
        "yellow_name": COLOR_NAME[YELLOW],
    }
    return data


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
    room["status"] = "finished" if g.finished else "playing"
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
