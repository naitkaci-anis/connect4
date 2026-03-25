from __future__ import annotations

import json
import os
import time
import math
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple, Dict, Any

# ============================================================
# Config / constantes jeu
# ============================================================

DEFAULT_CONFIG: Dict[str, Any] = {
    "rows": 8,
    "cols": 9,
    "starting_color": "R",
    "cell_size": 64,
    "margin": 18,
    "drop_delay_ms": 250,
}

CONFIG_PATH = "config.json"
SAVES_DIR = "saves"

RED = "R"
YELLOW = "Y"
EMPTY = "."

COLOR_NAME = {RED: "Rouge", YELLOW: "Jaune"}
COLOR_FILL = {RED: "#e53935", YELLOW: "#fdd835", EMPTY: "#ffffff"}


def ensure_config() -> Dict[str, Any]:
    """
    Crée config.json s'il n'existe pas, sinon le lit et le normalise.
    Retourne un dict propre (bornes appliquées).
    """
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        return dict(DEFAULT_CONFIG)

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = dict(DEFAULT_CONFIG)

    rows = int(cfg.get("rows", DEFAULT_CONFIG["rows"]))
    cols = int(cfg.get("cols", DEFAULT_CONFIG["cols"]))
    rows = max(4, min(rows, 30))
    cols = max(4, min(cols, 30))

    starting = cfg.get("starting_color", DEFAULT_CONFIG["starting_color"])
    starting = starting if starting in (RED, YELLOW) else DEFAULT_CONFIG["starting_color"]

    cell_size = int(cfg.get("cell_size", DEFAULT_CONFIG["cell_size"]))
    cell_size = max(30, min(cell_size, 120))

    margin = int(cfg.get("margin", DEFAULT_CONFIG["margin"]))
    margin = max(5, min(margin, 50))

    delay = int(cfg.get("drop_delay_ms", DEFAULT_CONFIG["drop_delay_ms"]))
    delay = max(0, min(delay, 2000))

    cfg2 = {
        "rows": rows,
        "cols": cols,
        "starting_color": starting,
        "cell_size": cell_size,
        "margin": margin,
        "drop_delay_ms": delay,
    }

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg2, f, indent=2, ensure_ascii=False)

    return cfg2


def next_game_index() -> int:
    """
    Incrémente un compteur persistant dans saves/_index.txt
    pour donner un numéro unique aux nouvelles parties.
    """
    path = os.path.join(SAVES_DIR, "_index.txt")
    os.makedirs(SAVES_DIR, exist_ok=True)

    n = 0
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                n = int(f.read().strip() or "0")
        except Exception:
            n = 0

    n += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(n))
    return n


# ============================================================
# Helpers de plateau
# ============================================================

def count_tokens(board: List[List[str]]) -> Tuple[int, int]:
    r_count = 0
    y_count = 0
    for row in board:
        for cell in row:
            if cell == RED:
                r_count += 1
            elif cell == YELLOW:
                y_count += 1
    return r_count, y_count


def infer_current_turn(board: List[List[str]], starting_color: str = RED) -> str:
    """
    Déduit à qui est le tour à partir du nombre de pions.
    Lève ValueError si le comptage est incohérent.
    """
    r_count, y_count = count_tokens(board)

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

    raise ValueError(
        f"Comptage incohérent pour starting_color={starting_color}: R={r_count}, Y={y_count}"
    )


# ============================================================
# Modèle / état de partie
# ============================================================

@dataclass
class Move:
    col: int
    row: int
    color: str
    timestamp: float


@dataclass
class GameSnapshot:
    rows: int
    cols: int
    starting_color: str
    current_turn: str
    board: List[List[str]]
    moves: List[Dict[str, Any]]
    cursor: int
    winner: Optional[str] = None
    winning_line: Optional[List[Tuple[int, int]]] = None
    finished: bool = False
    draw: bool = False
    game_index: int = 0
    mode: int = 2
    paused: bool = False


class Connect4:
    def __init__(self, rows: int, cols: int, starting_color: str):
        self.rows = rows
        self.cols = cols
        self.starting_color = starting_color
        self.reset(game_index=next_game_index(), mode=2)

    def reset(self, game_index: int, mode: int):
        self.board = [[EMPTY for _ in range(self.cols)] for _ in range(self.rows)]
        self.moves: List[Move] = []
        self.cursor = 0
        self.current_turn = self.starting_color
        self.winner: Optional[str] = None
        self.winning_line: Optional[List[Tuple[int, int]]] = None
        self.finished = False
        self.draw = False
        self.game_index = game_index
        self.mode = mode
        self.paused = False

    def can_play(self) -> bool:
        return (not self.finished) and (not self.paused)

    def valid_columns(self) -> List[int]:
        return [c for c in range(self.cols) if self.board[0][c] == EMPTY]

    def drop_in_column(self, col: int) -> bool:
        if not self.can_play():
            return False
        if col < 0 or col >= self.cols:
            return False
        if self.board[0][col] != EMPTY:
            return False

        # si on était "en arrière" (slider), on coupe le futur
        if self.cursor < len(self.moves):
            self.moves = self.moves[: self.cursor]

        row = self.rows - 1
        while row >= 0 and self.board[row][col] != EMPTY:
            row -= 1
        if row < 0:
            return False

        color = self.current_turn
        self.board[row][col] = color
        self.moves.append(Move(col=col, row=row, color=color, timestamp=time.time()))
        self.cursor += 1

        self._update_after_move(last_row=row, last_col=col, last_color=color)
        if not self.finished:
            self.current_turn = YELLOW if self.current_turn == RED else RED
        return True

    def _update_after_move(self, last_row: int, last_col: int, last_color: str):
        line = self.check_winner_from(last_row, last_col, last_color)
        if line:
            self.finished = True
            self.winner = last_color
            self.winning_line = line
            return

        if all(self.board[0][c] != EMPTY for c in range(self.cols)):
            self.finished = True
            self.draw = True

    def check_winner_from(
        self, r: int, c: int, color: str
    ) -> Optional[List[Tuple[int, int]]]:
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]

        for dr, dc in directions:
            cells = [(r, c)]

            rr, cc = r + dr, c + dc
            while (
                0 <= rr < self.rows
                and 0 <= cc < self.cols
                and self.board[rr][cc] == color
            ):
                cells.append((rr, cc))
                rr += dr
                cc += dc

            rr, cc = r - dr, c - dc
            while (
                0 <= rr < self.rows
                and 0 <= cc < self.cols
                and self.board[rr][cc] == color
            ):
                cells.append((rr, cc))
                rr -= dr
                cc -= dc

            if len(cells) >= 4:
                cells_sorted = sorted(cells, key=lambda x: (x[0] * dr + x[1] * dc))
                return cells_sorted[:4]

        return None

    def apply_to_cursor(self, cursor: int):
        cursor = max(0, min(cursor, len(self.moves)))

        self.board = [[EMPTY for _ in range(self.cols)] for _ in range(self.rows)]
        self.finished = False
        self.draw = False
        self.winner = None
        self.winning_line = None
        self.cursor = 0
        self.current_turn = self.starting_color

        for i in range(cursor):
            mv = self.moves[i]
            self.board[mv.row][mv.col] = mv.color
            self.cursor += 1
            self._update_after_move(mv.row, mv.col, mv.color)
            if self.finished:
                break
            self.current_turn = YELLOW if self.current_turn == RED else RED

    def undo(self):
        if self.cursor > 0:
            self.apply_to_cursor(self.cursor - 1)

    def redo(self):
        if self.cursor < len(self.moves):
            self.apply_to_cursor(self.cursor + 1)

    def to_snapshot(self) -> GameSnapshot:
        return GameSnapshot(
            rows=self.rows,
            cols=self.cols,
            starting_color=self.starting_color,
            current_turn=self.current_turn,
            board=[row[:] for row in self.board],
            moves=[asdict(m) for m in self.moves],
            cursor=self.cursor,
            winner=self.winner,
            winning_line=self.winning_line,
            finished=self.finished,
            draw=self.draw,
            game_index=self.game_index,
            mode=self.mode,
            paused=self.paused,
        )

    @staticmethod
    def from_snapshot(snap: GameSnapshot) -> "Connect4":
        g = Connect4(rows=snap.rows, cols=snap.cols, starting_color=snap.starting_color)
        g.game_index = snap.game_index
        g.mode = snap.mode
        g.paused = snap.paused
        g.moves = [Move(**m) for m in snap.moves]
        g.apply_to_cursor(snap.cursor)
        return g


# ============================================================
# Minimax / heuristiques
# ============================================================

def _opp(color: str) -> str:
    return RED if color == YELLOW else YELLOW


def _valid_cols(board: List[List[str]]) -> List[int]:
    cols = len(board[0])
    return [c for c in range(cols) if board[0][c] == EMPTY]


def _ordered_cols(board: List[List[str]]) -> List[int]:
    """
    Retourne les colonnes valides en testant d'abord le centre,
    puis les colonnes les plus proches du centre.
    """
    cols = len(board[0])
    center = cols // 2
    valid = _valid_cols(board)
    valid.sort(key=lambda c: abs(c - center))
    return valid


def _drop(board: List[List[str]], col: int, color: str) -> Optional[int]:
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


def _undo(board: List[List[str]], row: int, col: int) -> None:
    board[row][col] = EMPTY


def _is_win(board: List[List[str]], color: str) -> bool:
    rows = len(board)
    cols = len(board[0])

    # horizontal
    for r in range(rows):
        for c in range(cols - 3):
            if all(board[r][c + i] == color for i in range(4)):
                return True

    # vertical
    for c in range(cols):
        for r in range(rows - 3):
            if all(board[r + i][c] == color for i in range(4)):
                return True

    # diag /
    for r in range(3, rows):
        for c in range(cols - 3):
            if all(board[r - i][c + i] == color for i in range(4)):
                return True

    # diag \
    for r in range(rows - 3):
        for c in range(cols - 3):
            if all(board[r + i][c + i] == color for i in range(4)):
                return True

    return False


def _full(board: List[List[str]]) -> bool:
    return all(x != EMPTY for x in board[0])


def _playable_empty_count(win: List[str], playable_mask: List[bool]) -> int:
    c = 0
    for i in range(4):
        if win[i] == EMPTY and playable_mask[i]:
            c += 1
    return c


def _score_window(win: List[str], playable_mask: List[bool], ai: str) -> int:
    """
    Heuristique :
    - récompense les menaces jouables immédiatement
    - pénalise davantage les menaces adverses
    - valorise aussi les structures préparatoires
    """
    opp = _opp(ai)
    a = win.count(ai)
    o = win.count(opp)
    e = win.count(EMPTY)
    playable_empties = _playable_empty_count(win, playable_mask)

    if a == 4:
        return 1_000_000
    if o == 4:
        return -1_000_000

    # Cas purs IA
    if o == 0:
        if a == 3 and e == 1:
            return 15_000 if playable_empties == 1 else 2_000
        if a == 2 and e == 2:
            return 300 if playable_empties >= 1 else 80
        if a == 1 and e == 3:
            return 8

    # Cas purs adverses
    if a == 0:
        if o == 3 and e == 1:
            return -18_000 if playable_empties == 1 else -2_500
        if o == 2 and e == 2:
            return -350 if playable_empties >= 1 else -90
        if o == 1 and e == 3:
            return -10

    return 0


def _count_immediate_wins(board: List[List[str]], color: str) -> int:
    """
    Compte le nombre de colonnes qui donnent une victoire immédiate.
    Utile pour détecter les doubles menaces.
    """
    count = 0
    for c in _valid_cols(board):
        r = _drop(board, c, color)
        if r is None:
            continue
        if _is_win(board, color):
            count += 1
        _undo(board, r, c)
    return count


def immediate_winning_columns(board: List[List[str]], color: str) -> List[int]:
    """
    Retourne la liste des colonnes qui gagnent immédiatement.
    """
    wins: List[int] = []
    for c in _valid_cols(board):
        r = _drop(board, c, color)
        if r is None:
            continue
        if _is_win(board, color):
            wins.append(c)
        _undo(board, r, c)
    return wins


def _eval(board: List[List[str]], ai: str) -> int:
    rows = len(board)
    cols = len(board[0])
    opp = _opp(ai)
    score = 0

    # 1) Priorité au centre et aux colonnes proches du centre
    center = cols // 2
    for c in range(cols):
        weight = cols - abs(c - center)
        for r in range(rows):
            if board[r][c] == ai:
                score += weight * 10
            elif board[r][c] == opp:
                score -= weight * 10

    # 2) Fenêtres de 4 avec notion de case jouable
    # horizontal
    for r in range(rows):
        for c in range(cols - 3):
            win = [board[r][c + i] for i in range(4)]
            playable_mask = []
            for i in range(4):
                rr = r
                cc = c + i
                playable = board[rr][cc] == EMPTY and (rr == rows - 1 or board[rr + 1][cc] != EMPTY)
                playable_mask.append(playable)
            score += _score_window(win, playable_mask, ai)

    # vertical
    for c in range(cols):
        for r in range(rows - 3):
            win = [board[r + i][c] for i in range(4)]
            playable_mask = []
            for i in range(4):
                rr = r + i
                cc = c
                playable = board[rr][cc] == EMPTY and (rr == rows - 1 or board[rr + 1][cc] != EMPTY)
                playable_mask.append(playable)
            score += _score_window(win, playable_mask, ai)

    # diag /
    for r in range(3, rows):
        for c in range(cols - 3):
            cells = [(r - i, c + i) for i in range(4)]
            win = [board[rr][cc] for rr, cc in cells]
            playable_mask = []
            for rr, cc in cells:
                playable = board[rr][cc] == EMPTY and (rr == rows - 1 or board[rr + 1][cc] != EMPTY)
                playable_mask.append(playable)
            score += _score_window(win, playable_mask, ai)

    # diag \
    for r in range(rows - 3):
        for c in range(cols - 3):
            cells = [(r + i, c + i) for i in range(4)]
            win = [board[rr][cc] for rr, cc in cells]
            playable_mask = []
            for rr, cc in cells:
                playable = board[rr][cc] == EMPTY and (rr == rows - 1 or board[rr + 1][cc] != EMPTY)
                playable_mask.append(playable)
            score += _score_window(win, playable_mask, ai)

    # 3) Menaces immédiates / doubles menaces
    ai_wins = _count_immediate_wins(board, ai)
    opp_wins = _count_immediate_wins(board, opp)

    score += ai_wins * 25_000
    score -= opp_wins * 30_000

    if ai_wins >= 2:
        score += 200_000
    if opp_wins >= 2:
        score -= 220_000

    return score


def _minimax(
    board: List[List[str]],
    depth: int,
    alpha: int,
    beta: int,
    maximizing: bool,
    ai: str,
) -> int:
    opp = _opp(ai)

    if _is_win(board, ai):
        return 10_000_000 + depth
    if _is_win(board, opp):
        return -10_000_000 - depth
    if depth == 0 or _full(board):
        return _eval(board, ai)

    moves = _ordered_cols(board)

    if maximizing:
        value = -math.inf
        for c in moves:
            r = _drop(board, c, ai)
            if r is None:
                continue
            child = _minimax(board, depth - 1, alpha, beta, False, ai)
            _undo(board, r, c)
            value = max(value, child)
            alpha = max(alpha, value)
            if alpha >= beta:
                break
        return int(value)

    value = math.inf
    for c in moves:
        r = _drop(board, c, opp)
        if r is None:
            continue
        child = _minimax(board, depth - 1, alpha, beta, True, ai)
        _undo(board, r, c)
        value = min(value, child)
        beta = min(beta, value)
        if alpha >= beta:
            break
    return int(value)


def minimax_score_for_column(
    board: List[List[str]],
    col: int,
    depth: int,
    ai: str,
) -> Optional[int]:
    """
    Score d'une colonne pour l'IA :
    - gagner immédiatement si possible
    - éviter les colonnes qui donnent une victoire immédiate à l'adversaire
    """
    if board[0][col] != EMPTY:
        return None

    opp = _opp(ai)

    r = _drop(board, col, ai)
    if r is None:
        return None

    # Si ce coup gagne tout de suite, priorité absolue
    if _is_win(board, ai):
        _undo(board, r, col)
        return 99_999_999

    # Si après notre coup l'adversaire a une réponse gagnante immédiate,
    # on pénalise très fort
    opp_immediate_wins = _count_immediate_wins(board, opp)
    if opp_immediate_wins > 0:
        sc = -50_000_000 - opp_immediate_wins * 100_000
    else:
        sc = _minimax(board, depth - 1, -(10**18), 10**18, False, ai)

    _undo(board, r, col)
    return sc


def pick_best(scores: List[Optional[int]]) -> int:
    """
    Choisit la meilleure colonne.
    En cas d'égalité, préfère le centre.
    """
    cols = len(scores)
    center = cols // 2
    candidates = [(c, s) for c, s in enumerate(scores) if s is not None]
    if not candidates:
        raise ValueError("Aucun score valide dans pick_best")
    candidates.sort(key=lambda cs: (cs[1], -abs(cs[0] - center)))
    return candidates[-1][0]
