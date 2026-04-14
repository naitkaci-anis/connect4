from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import json
import secrets
import threading
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
    game = Connect4(cfg["rows"], cfg["cols"], cfg["starting_color"])
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
# Prédiction MiniMax (bouton 🔮 Prédire)
# ============================================================

@app.get("/api/predict")
def api_predict():
    g = game

    if g.finished:
        if g.draw:
            return {"winner": "draw", "moves_left": 0, "explanation": "Partie terminée : égalité."}
        return {"winner": g.winner, "moves_left": 0,
                "explanation": f"Partie terminée : {COLOR_NAME[g.winner]} a gagné."}

    ai = g.current_turn
    opp = YELLOW if ai == RED else RED
    tmp = [row[:] for row in g.board]

    for c in range(g.cols):
        if tmp[0][c] != EMPTY:
            continue
        r = None
        for rr in range(g.rows - 1, -1, -1):
            if tmp[rr][c] == EMPTY:
                r = rr
                break
        if r is None:
            continue
        tmp[r][c] = ai
        if _is_win(tmp, ai):
            tmp[r][c] = EMPTY
            return {"winner": ai, "moves_left": 1,
                    "explanation": f"{COLOR_NAME[ai]} gagne au prochain coup."}
        tmp[r][c] = EMPTY

    max_depth = 6
    found_forced = None
    fallback_best_score = -10**18
    deadline = time.time() + 1.5

    for depth in range(2, max_depth + 1):
        best_score = -10**18
        for c in range(g.cols):
            if time.time() > deadline:
                break
            sc = minimax_score_for_column(tmp, c, depth, ai)
            if sc is not None and sc > best_score:
                best_score = sc
        fallback_best_score = best_score

        if best_score >= 9_000_000:
            found_forced = (ai, depth, depth, best_score)
            break
        if best_score <= -9_000_000:
            found_forced = (opp, depth, depth, best_score)
            break

    if found_forced is not None:
        winner, moves_left, used_depth, raw_score = found_forced
        approx_turns = max(1, (moves_left + 1) // 2)
        return {"winner": winner, "moves_left": moves_left, "finished": False,
                "score": 9999,
                "explanation": f"{COLOR_NAME[winner]} gagne dans environ {approx_turns} tour(s)."}

    if fallback_best_score > 50_000:
        return {"winner": ai, "moves_left": -1, "finished": False,
                "score": int(min(fallback_best_score, 500_000)),
                "explanation": f"{COLOR_NAME[ai]} est en avantage."}
    if fallback_best_score < -50_000:
        return {"winner": opp, "moves_left": -1, "finished": False,
                "score": int(max(fallback_best_score, -500_000)),
                "explanation": f"{COLOR_NAME[opp]} est en avantage."}

    return {"winner": "unknown", "moves_left": -1, "finished": False,
            "score": int(fallback_best_score) if fallback_best_score != -10**18 else 0,
            "explanation": "Position équilibrée, aucun avantage clair."}


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

    new_game = Connect4(rows_n, cols_n, game.starting_color)
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
