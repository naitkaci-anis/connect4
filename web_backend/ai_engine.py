"""
ai_engine.py — MiniMax profondeur PROGRESSIVE + Blocage/Victoire prioritaires
==============================================================================
Ordre de priorité STRICT :
  1. Gagner en 1 coup         → joue immédiatement
  2. Bloquer victoire adverse → bloque immédiatement
  3. MiniMax (profondeur progressive)

La profondeur progressive :
  depth 1-4 → fixe toute la partie
  depth 5   → coups 0-3:depth3  4-7:depth4  8+:depth5
  depth 6   → coups 0-3:depth4  4-7:depth5  8+:depth6
  depth 7   → coups 0-3:depth4  4-7:depth5  8-11:depth6  12+:depth7
  depth 8   → coups 0-3:depth4  4-7:depth5  8-11:depth6  12-15:depth7  16+:depth8
"""

from __future__ import annotations
import math
from typing import List, Optional

RED    = "R"
YELLOW = "Y"
EMPTY  = "."


# ══════════════════════════════════════════════════════════════
# PROFONDEUR EFFECTIVE
# ══════════════════════════════════════════════════════════════

def _effective_depth(depth: int, cursor: int) -> int:
    if depth <= 4:
        return depth
    start = 3 if depth == 5 else 4
    phase = cursor // 4
    return min(start + phase, depth)


# ══════════════════════════════════════════════════════════════
# HELPERS PLATEAU
# ══════════════════════════════════════════════════════════════

def _opp(color: str) -> str:
    return RED if color == YELLOW else YELLOW


def _valid_cols(board: List[List[str]]) -> List[int]:
    return [c for c in range(len(board[0])) if board[0][c] == EMPTY]


def _ordered_cols(board: List[List[str]]) -> List[int]:
    cols   = len(board[0])
    center = cols // 2
    valid  = _valid_cols(board)
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
    # diag backslash
    for r in range(rows - 3):
        for c in range(cols - 3):
            if all(board[r + i][c + i] == color for i in range(4)):
                return True
    return False


def _full(board: List[List[str]]) -> bool:
    return all(x != EMPTY for x in board[0])


def _winning_moves(board: List[List[str]], color: str) -> List[int]:
    """Retourne toutes les colonnes où `color` gagne en 1 coup."""
    wins = []
    for c in _valid_cols(board):
        r = _drop(board, c, color)
        if r is not None:
            if _is_win(board, color):
                wins.append(c)
            _undo(board, r, c)
    return wins


# ══════════════════════════════════════════════════════════════
# HEURISTIQUE
# ══════════════════════════════════════════════════════════════

def _score_window(win: List[str], ai: str) -> int:
    opp = _opp(ai)
    a = win.count(ai)
    o = win.count(opp)
    e = win.count(EMPTY)
    if a == 4: return  1_000_000
    if o == 4: return -1_000_000
    if o == 0:
        if a == 3 and e == 1: return  5_000
        if a == 2 and e == 2: return    200
        if a == 1 and e == 3: return      5
    if a == 0:
        if o == 3 and e == 1: return -8_000
        if o == 2 and e == 2: return   -300
        if o == 1 and e == 3: return    -10
    return 0


def _eval(board: List[List[str]], ai: str) -> int:
    rows   = len(board)
    cols   = len(board[0])
    opp    = _opp(ai)
    center = cols // 2
    score  = 0

    for c in range(cols):
        w = cols - abs(c - center)
        for r in range(rows):
            if   board[r][c] == ai:  score += w * 3
            elif board[r][c] == opp: score -= w * 3

    for r in range(rows):
        for c in range(cols - 3):
            score += _score_window([board[r][c + i] for i in range(4)], ai)
    for c in range(cols):
        for r in range(rows - 3):
            score += _score_window([board[r + i][c] for i in range(4)], ai)
    for r in range(3, rows):
        for c in range(cols - 3):
            score += _score_window([board[r - i][c + i] for i in range(4)], ai)
    for r in range(rows - 3):
        for c in range(cols - 3):
            score += _score_window([board[r + i][c + i] for i in range(4)], ai)

    return score


# ══════════════════════════════════════════════════════════════
# MINIMAX ALPHA-BETA
# ══════════════════════════════════════════════════════════════

def _minimax(
    board     : List[List[str]],
    depth     : int,
    alpha     : int,
    beta      : int,
    maximizing: bool,
    ai        : str,
) -> int:
    opp = _opp(ai)

    if _is_win(board, ai):  return  10_000_000 + depth
    if _is_win(board, opp): return -10_000_000 - depth
    if depth == 0 or _full(board): return _eval(board, ai)

    moves = _ordered_cols(board)

    if maximizing:
        value = -math.inf
        for c in moves:
            r = _drop(board, c, ai)
            if r is None: continue
            value = max(value, _minimax(board, depth - 1, alpha, beta, False, ai))
            _undo(board, r, c)
            alpha = max(alpha, value)
            if alpha >= beta: break
        return int(value)
    else:
        value = math.inf
        for c in moves:
            r = _drop(board, c, opp)
            if r is None: continue
            value = min(value, _minimax(board, depth - 1, alpha, beta, True, ai))
            _undo(board, r, c)
            beta = min(beta, value)
            if alpha >= beta: break
        return int(value)


# ══════════════════════════════════════════════════════════════
# SCORE PAR COLONNE (utilisé uniquement si aucune vic/bloc immédiate)
# ══════════════════════════════════════════════════════════════

def _score_col(board: List[List[str]], col: int, depth: int, ai: str) -> Optional[int]:
    """
    Score minimax pour une colonne.
    NB : victoire/blocage immédiats sont déjà gérés AVANT d'appeler cette fonction.
    Ici on gère uniquement les positions sans menace immédiate.
    """
    if board[0][col] != EMPTY:
        return None

    opp = _opp(ai)
    r   = _drop(board, col, ai)
    if r is None:
        return None

    # Victoire immédiate (sécurité, ne devrait pas arriver ici)
    if _is_win(board, ai):
        _undo(board, r, col)
        return 99_999_999

    # Compter les menaces adverses restantes après ce coup
    opp_threats = len(_winning_moves(board, opp))

    if opp_threats >= 2:
        # Double menace impossible à bloquer → très mauvais mais inévitable
        sc = -20_000_000 - opp_threats * 1_000_000
    elif opp_threats == 1:
        # Une menace reste → pénalité mais moins sévère (le minimax peut l'évaluer)
        sc = _minimax(board, depth - 1, -(10**18), 10**18, False, ai) - 5_000_000
    else:
        # Aucune menace immédiate → minimax pur
        sc = _minimax(board, depth - 1, -(10**18), 10**18, False, ai)

    _undo(board, r, col)
    return sc


def _pick_best(scores: List[Optional[int]], cols: int) -> int:
    center     = cols // 2
    candidates = [(c, s) for c, s in enumerate(scores) if s is not None]
    if not candidates:
        raise ValueError("Aucun score valide")
    candidates.sort(key=lambda cs: (cs[1], -abs(cs[0] - center)))
    return candidates[-1][0]


# ══════════════════════════════════════════════════════════════
# POINT D'ENTRÉE PRINCIPAL
# ══════════════════════════════════════════════════════════════

def choose_column(
    board        : List[List[str]],
    current_turn : str,
    rows         : int,
    cols         : int,
    depth        : int = 4,
    cursor       : int = 0,
    **kwargs,
) -> int:
    ai  = current_turn
    opp = _opp(ai)

    eff_depth = _effective_depth(depth, cursor)

    tmp   = [row[:] for row in board]
    valid = _valid_cols(tmp)

    if not valid:
        raise ValueError("Aucune colonne jouable")
    if len(valid) == 1:
        return valid[0]

    # ══ PRIORITÉ 1 : Victoire immédiate ══════════════════════
    # Si l'IA peut gagner en 1 coup → joue IMMÉDIATEMENT
    ai_wins = _winning_moves(tmp, ai)
    if ai_wins:
        return ai_wins[0]

    # ══ PRIORITÉ 2 : Blocage immédiat ════════════════════════
    # Si l'adversaire peut gagner en 1 coup → bloque IMMÉDIATEMENT
    opp_wins = _winning_moves(tmp, opp)
    if opp_wins:
        # Si l'adversaire a 2+ victoires possibles → double menace,
        # bloquer la plus centrale
        opp_wins.sort(key=lambda c: abs(c - cols // 2))
        return opp_wins[0]

    # ══ PRIORITÉ 3 : MiniMax à profondeur progressive ════════
    print(f"[MiniMax] depth={depth} | cursor={cursor} | eff_depth={eff_depth}")
    scores = [_score_col(tmp, c, eff_depth, ai) for c in range(cols)]
    return _pick_best(scores, cols)


# ══════════════════════════════════════════════════════════════
# INTERFACE server.py
# ══════════════════════════════════════════════════════════════

def ai_choose_column_from_game(
    game,
    db_available : bool = False,
    robot_depth  : int  = 4,
    mode         : str  = "minimax",
) -> int:
    return choose_column(
        board        = game.board,
        current_turn = game.current_turn,
        rows         = game.rows,
        cols         = game.cols,
        depth        = robot_depth,
        cursor       = game.cursor,
    )
