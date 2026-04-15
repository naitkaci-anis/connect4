"""
neural_ai.py — IA hybride rapide avec mix ciblé
================================================
Objectif de conception (en moyenne globale, sur beaucoup de parties) :
- ~70% modèle pur
- ~20% règles tactiques directes
- ~10% MiniMax

Ce ne sont pas des garanties exactes par partie, mais des proportions
visées par la logique de décision.

Points corrigés :
- 1er coup = centre obligatoire
- ouverture plus solide quand l'IA commence
- modèle toujours utilisé
- MiniMax rare et court pour rester rapide
- compteur intégré pour mesurer la vraie répartition
"""

from __future__ import annotations

import os
import json
import math
import time
from typing import Optional, List, Tuple, Dict, Any

import torch
import torch.nn as nn

ROWS = 9
COLS = 9
RED = "R"
YELLOW = "Y"
EMPTY = "."

WIN_SCORE = 10_000_000


# ════════════════════════════════════════════
# ARCHITECTURE COMPATIBLE AVEC TON MODÈLE
# ════════════════════════════════════════════

class ResBlock(nn.Module):
    def __init__(self, ch: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(ch, ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(ch),
            nn.ReLU(inplace=True),
            nn.Conv2d(ch, ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(ch),
        )
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        return self.relu(x + self.net(x))


class Connect4Net(nn.Module):
    def __init__(self, rows=ROWS, cols=COLS, in_ch=3, filters=128, blocks=6):
        super().__init__()
        self.rows = rows
        self.cols = cols

        self.stem = nn.Sequential(
            nn.Conv2d(in_ch, filters, 3, padding=1, bias=False),
            nn.BatchNorm2d(filters),
            nn.ReLU(inplace=True),
        )
        self.body = nn.Sequential(*[ResBlock(filters) for _ in range(blocks)])
        self.policy_head = nn.Sequential(
            nn.Conv2d(filters, 32, 1, bias=False),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.Flatten(),
            nn.Linear(32 * rows * cols, cols),
        )
        self.value_head = nn.Sequential(
            nn.Conv2d(filters, 1, 1, bias=False),
            nn.BatchNorm2d(1),
            nn.ReLU(inplace=True),
            nn.Flatten(),
            nn.Linear(rows * cols, 64),
            nn.ReLU(inplace=True),
            nn.Linear(64, 1),
            nn.Tanh(),
        )

    def forward(self, x):
        t = self.body(self.stem(x))
        return self.policy_head(t), self.value_head(t)


# ════════════════════════════════════════════
# HELPERS JEU
# ════════════════════════════════════════════

def _opp(color: str) -> str:
    return YELLOW if color == RED else RED


def _valid(board: List[List[str]], cols: int) -> List[int]:
    return [c for c in range(cols) if board[0][c] == EMPTY]


def _ordered_center(valid_cols: List[int], cols: int) -> List[int]:
    center = cols // 2
    return sorted(valid_cols, key=lambda c: abs(c - center))


def _drop(board: List[List[str]], col: int, color: str, rows: int) -> int:
    for r in range(rows - 1, -1, -1):
        if board[r][col] == EMPTY:
            board[r][col] = color
            return r
    return -1


def _undo(board: List[List[str]], row: int, col: int) -> None:
    board[row][col] = EMPTY


def _win(board: List[List[str]], color: str, rows: int, cols: int) -> bool:
    for r in range(rows):
        for c in range(cols):
            if board[r][c] != color:
                continue
            for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
                ok = True
                for k in range(1, 4):
                    nr, nc = r + k * dr, c + k * dc
                    if not (0 <= nr < rows and 0 <= nc < cols and board[nr][nc] == color):
                        ok = False
                        break
                if ok:
                    return True
    return False


def _winning_moves(board: List[List[str]], color: str, rows: int, cols: int) -> List[int]:
    wins = []
    for c in _valid(board, cols):
        r = _drop(board, c, color, rows)
        if r >= 0:
            if _win(board, color, rows, cols):
                wins.append(c)
            _undo(board, r, c)
    return wins


def _score_window(win4: List[str], ai: str) -> int:
    opp = _opp(ai)
    a = win4.count(ai)
    o = win4.count(opp)
    e = win4.count(EMPTY)

    if a == 4:
        return 1_000_000
    if o == 4:
        return -1_000_000

    if o == 0:
        if a == 3 and e == 1:
            return 5000
        if a == 2 and e == 2:
            return 220
        if a == 1 and e == 3:
            return 8

    if a == 0:
        if o == 3 and e == 1:
            return -7000
        if o == 2 and e == 2:
            return -260
        if o == 1 and e == 3:
            return -10

    return 0


def _heuristic(board: List[List[str]], ai: str, rows: int, cols: int) -> int:
    opp = _opp(ai)
    center = cols // 2
    score = 0

    # Bonus centre
    for c in range(cols):
        w = cols - abs(c - center)
        for r in range(rows):
            if board[r][c] == ai:
                score += w * 4
            elif board[r][c] == opp:
                score -= w * 4

    # Fenêtres de 4
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


# ════════════════════════════════════════════
# IA PRINCIPALE
# ════════════════════════════════════════════

class NeuralAI:
    _instance = None

    def __init__(self, model_path: str, info_path: Optional[str] = None):
        self.device = torch.device("cpu")

        info = {
            "rows": ROWS,
            "cols": COLS,
            "in_channels": 3,
            "num_filters": 128,
            "num_res_blocks": 6,
        }
        if info_path and os.path.exists(info_path):
            with open(info_path, encoding="utf-8") as f:
                info.update(json.load(f))

        self.rows = int(info.get("rows", ROWS))
        self.cols = int(info.get("cols", COLS))

        self.model = Connect4Net(
            rows=self.rows,
            cols=self.cols,
            in_ch=int(info.get("in_channels", 3)),
            filters=int(info.get("num_filters", 128)),
            blocks=int(info.get("num_res_blocks", 6)),
        ).to(self.device)

        self.model.load_state_dict(torch.load(model_path, map_location=self.device))
        self.model.eval()

        self._policy_cache: Dict[Tuple[Tuple[str, ...], str], List[float]] = {}

        # Stats réelles d'utilisation
        self.stats: Dict[str, int] = {
            "model": 0,
            "rules": 0,
            "minimax": 0,
        }
        self.last_reason: str = "init"

        print(
            f"✅ NeuralAI chargée — "
            f"filters={info.get('num_filters')} blocks={info.get('num_res_blocks')}"
        )

    @classmethod
    def get_instance(cls) -> Optional["NeuralAI"]:
        if cls._instance is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            model_path = os.path.join(script_dir, "connect4_model.pt")
            info_path = os.path.join(script_dir, "connect4_model_info.json")

            if not os.path.exists(model_path):
                print(f"⚠️ connect4_model.pt introuvable dans {script_dir}")
                return None

            try:
                cls._instance = cls(model_path, info_path)
            except Exception as e:
                print(f"⚠️ Impossible de charger NeuralAI : {e}")
                return None

        return cls._instance

    # ─────────────────────────────────────
    # Stats
    # ─────────────────────────────────────

    def _mark(self, branch: str, reason: str) -> None:
        if branch not in self.stats:
            self.stats[branch] = 0
        self.stats[branch] += 1
        self.last_reason = reason

    def get_stats(self) -> Dict[str, Any]:
        total = sum(self.stats.values())
        if total <= 0:
            return {
                "counts": dict(self.stats),
                "percentages": {"model": 0.0, "rules": 0.0, "minimax": 0.0},
                "total": 0,
                "last_reason": self.last_reason,
            }

        return {
            "counts": dict(self.stats),
            "percentages": {
                "model": round(100.0 * self.stats.get("model", 0) / total, 2),
                "rules": round(100.0 * self.stats.get("rules", 0) / total, 2),
                "minimax": round(100.0 * self.stats.get("minimax", 0) / total, 2),
            },
            "total": total,
            "last_reason": self.last_reason,
        }

    def reset_stats(self) -> Dict[str, Any]:
        self.stats = {"model": 0, "rules": 0, "minimax": 0}
        self.last_reason = "reset"
        return self.get_stats()

    # ─────────────────────────────────────
    # Modèle
    # ─────────────────────────────────────

    def _board_key(self, board: List[List[str]]) -> Tuple[str, ...]:
        return tuple("".join(row) for row in board)

    def _board_to_tensor(self, board: List[List[str]], turn: str) -> torch.Tensor:
        rows = len(board)
        cols = len(board[0]) if board else self.cols

        r_p = torch.zeros(rows, cols, dtype=torch.float32)
        y_p = torch.zeros(rows, cols, dtype=torch.float32)

        for i in range(rows):
            for j in range(cols):
                if board[i][j] == RED:
                    r_p[i, j] = 1.0
                elif board[i][j] == YELLOW:
                    y_p[i, j] = 1.0

        me = r_p if turn == RED else y_p
        opp = y_p if turn == RED else r_p
        turn_plane = torch.ones(rows, cols, dtype=torch.float32)

        return torch.stack([me, opp, turn_plane], 0).unsqueeze(0)

    def _policy_logits(self, board: List[List[str]], turn: str) -> List[float]:
        key = (self._board_key(board), turn)
        if key in self._policy_cache:
            return self._policy_cache[key]

        with torch.no_grad():
            logits, _ = self.model(self._board_to_tensor(board, turn).to(self.device))

        out = logits.squeeze(0).detach().cpu().tolist()
        self._policy_cache[key] = out
        return out

    def _ordered_by_model(
        self,
        board: List[List[str]],
        turn: str,
        valid_cols: List[int],
        cols: int,
    ) -> List[int]:
        center = cols // 2
        logits = self._policy_logits(board, turn)

        scored = []
        for c in valid_cols:
            s = float(logits[c])
            # léger bonus centre pour stabiliser l'ouverture
            s += 0.18 * (center - abs(c - center))
            scored.append((s, c))

        scored.sort(reverse=True)
        return [c for _, c in scored]

    # ─────────────────────────────────────
    # MiniMax court et rapide
    # ─────────────────────────────────────

    def _minimax(
        self,
        board: List[List[str]],
        depth: int,
        alpha: float,
        beta: float,
        maximizing: bool,
        ai: str,
        rows: int,
        cols: int,
        deadline: float,
    ) -> float:
        opp = _opp(ai)

        if time.perf_counter() >= deadline:
            return float(_heuristic(board, ai, rows, cols))

        if _win(board, ai, rows, cols):
            return float(WIN_SCORE + depth)
        if _win(board, opp, rows, cols):
            return float(-WIN_SCORE - depth)

        valid = _valid(board, cols)
        if not valid:
            return 0.0
        if depth == 0:
            return float(_heuristic(board, ai, rows, cols))

        ordered = _ordered_center(valid, cols)

        if maximizing:
            value = -math.inf
            for c in ordered:
                if time.perf_counter() >= deadline:
                    break
                r = _drop(board, c, ai, rows)
                if r < 0:
                    continue
                score = self._minimax(board, depth - 1, alpha, beta, False, ai, rows, cols, deadline)
                _undo(board, r, c)

                if score > value:
                    value = score
                if value > alpha:
                    alpha = value
                if alpha >= beta:
                    break
            return float(value)

        value = math.inf
        for c in ordered:
            if time.perf_counter() >= deadline:
                break
            r = _drop(board, c, opp, rows)
            if r < 0:
                continue
            score = self._minimax(board, depth - 1, alpha, beta, True, ai, rows, cols, deadline)
            _undo(board, r, c)

            if score < value:
                value = score
            if value < beta:
                beta = value
            if alpha >= beta:
                break
        return float(value)

    def _best_by_search(
        self,
        board: List[List[str]],
        turn: str,
        candidate_cols: List[int],
        rows: int,
        cols: int,
        depth: int,
        time_budget: float,
    ) -> int:
        if not candidate_cols:
            raise ValueError("Aucun coup candidat")

        deadline = time.perf_counter() + time_budget
        best_col = candidate_cols[0]
        best_score = -math.inf

        # Petite iterative deepening
        for d in range(1, depth + 1):
            if time.perf_counter() >= deadline:
                break

            local_best_col = best_col
            local_best_score = -math.inf
            completed = True

            for rank, c in enumerate(candidate_cols):
                if time.perf_counter() >= deadline:
                    completed = False
                    break

                b = [row[:] for row in board]
                r = _drop(b, c, turn, rows)
                if r < 0:
                    continue

                if _win(b, turn, rows, cols):
                    score = float(WIN_SCORE + d)
                else:
                    score = self._minimax(
                        b,
                        d - 1,
                        -math.inf,
                        math.inf,
                        False,
                        turn,
                        rows,
                        cols,
                        deadline,
                    )

                # Léger bonus du classement du modèle pour départager
                score += 0.0001 * (len(candidate_cols) - rank)

                if score > local_best_score:
                    local_best_score = score
                    local_best_col = c

            if completed:
                best_col = local_best_col
                best_score = local_best_score
                candidate_cols = [best_col] + [c for c in candidate_cols if c != best_col]

                if best_score >= WIN_SCORE // 2:
                    break

        return best_col

    # ─────────────────────────────────────
    # Sélection finale
    # ─────────────────────────────────────

    def choose_column(
        self,
        board: List[List[str]],
        turn: str,
        valid_cols: Optional[List[int]] = None,
        cursor: int = 0,
    ) -> int:
        rows = len(board)
        cols = len(board[0]) if board else self.cols

        if valid_cols is None:
            valid_cols = _valid(board, cols)

        if not valid_cols:
            return 0
        if len(valid_cols) == 1:
            return valid_cols[0]

        self._policy_cache = {}
        opp = _opp(turn)
        center = cols // 2

        # ── 1) RÈGLES TACTIQUES DIRECTES (~20%) ──────────────────────────

        # Premier coup : toujours centre
        if cursor == 0 and center in valid_cols:
            self._mark("rules", "first_move_center")
            return center

        # Victoire immédiate
        wins = _winning_moves(board, turn, rows, cols)
        if wins:
            move = _ordered_center(wins, cols)[0]
            self._mark("rules", "immediate_win")
            return move

        # Blocage immédiat
        opp_wins = _winning_moves(board, opp, rows, cols)
        if opp_wins:
            move = _ordered_center(opp_wins, cols)[0]
            self._mark("rules", "immediate_block")
            return move

        # ── 2) MODÈLE D'ABORD (~70%) ─────────────────────────────────────

        model_order = self._ordered_by_model(board, turn, valid_cols, cols)
        neural_col = model_order[0]

        # Vérifier si le meilleur coup du modèle est suicidaire
        b_model = [row[:] for row in board]
        r_model = _drop(b_model, neural_col, turn, rows)
        suicidal = False
        if r_model >= 0:
            if len(_winning_moves(b_model, opp, rows, cols)) > 0:
                suicidal = True
            _undo(b_model, r_model, neural_col)

        # ── 3) MiniMax RARE ET COURT (~10%) ─────────────────────────────

        # Cas 1 : ouverture courte, mais seulement sur 2 décisions
        # pour ne pas exploser le pourcentage MiniMax
        if cursor in (1, 2):
            candidates = model_order[:3]
            move = self._best_by_search(
                board=board,
                turn=turn,
                candidate_cols=candidates,
                rows=rows,
                cols=cols,
                depth=3,
                time_budget=0.10,
            )
            self._mark("minimax", "opening_small_search")
            return move

        # Cas 2 : si le coup modèle est suicidaire, on essaye d'abord
        # un autre coup sûr selon le modèle → reste dans la logique "règle"
        if suicidal:
            for c in model_order[1:4]:
                b = [row[:] for row in board]
                r = _drop(b, c, turn, rows)
                if r < 0:
                    continue
                if len(_winning_moves(b, opp, rows, cols)) == 0:
                    _undo(b, r, c)
                    self._mark("rules", "anti_suicide_safe_model")
                    return c
                _undo(b, r, c)

            # Si aucun coup sûr simple, petit MiniMax de secours
            candidates = model_order[:4]
            move = self._best_by_search(
                board=board,
                turn=turn,
                candidate_cols=candidates,
                rows=rows,
                cols=cols,
                depth=4,
                time_budget=0.14,
            )
            self._mark("minimax", "anti_suicide_fallback")
            return move

        # Cas 3 : menaces multiples adverses = vraie urgence tactique
        # => MiniMax, mais sur peu de coups candidats
        danger = 0
        for c in valid_cols:
            b = [row[:] for row in board]
            r = _drop(b, c, opp, rows)
            if r >= 0:
                if _win(b, opp, rows, cols):
                    danger += 1
                _undo(b, r, c)

        if danger >= 2:
            candidates = model_order[:4]
            move = self._best_by_search(
                board=board,
                turn=turn,
                candidate_cols=candidates,
                rows=rows,
                cols=cols,
                depth=4,
                time_budget=0.16,
            )
            self._mark("minimax", "double_threat_defense")
            return move

        # ── 4) MODÈLE PUR ────────────────────────────────────────────────
        self._mark("model", "pure_model")
        return neural_col


# ════════════════════════════════════════════
# INTERFACE POUR server.py
# ════════════════════════════════════════════

def ai_choose_column_neural(game) -> int:
    ai = NeuralAI.get_instance()
    if ai is None:
        from ai_engine import ai_choose_column_from_game
        return ai_choose_column_from_game(game, db_available=False, robot_depth=4, mode="minimax")

    board = game.board
    turn = game.current_turn
    valid_cols = game.valid_columns()
    cursor = int(getattr(game, "cursor", 0))

    return ai.choose_column(board, turn, valid_cols, cursor)


# ════════════════════════════════════════════
# FONCTIONS OPTIONNELLES POUR LIRE LES STATS
# ════════════════════════════════════════════

def ai_get_neural_usage_stats() -> Dict[str, Any]:
    ai = NeuralAI.get_instance()
    if ai is None:
        return {
            "counts": {"model": 0, "rules": 0, "minimax": 0},
            "percentages": {"model": 0.0, "rules": 0.0, "minimax": 0.0},
            "total": 0,
            "last_reason": "model_not_loaded",
        }
    return ai.get_stats()


def ai_reset_neural_usage_stats() -> Dict[str, Any]:
    ai = NeuralAI.get_instance()
    if ai is None:
        return {
            "counts": {"model": 0, "rules": 0, "minimax": 0},
            "percentages": {"model": 0.0, "rules": 0.0, "minimax": 0.0},
            "total": 0,
            "last_reason": "model_not_loaded",
        }
    return ai.reset_stats()
