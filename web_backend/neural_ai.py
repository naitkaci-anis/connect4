"""
neural_ai.py  —  Intégration du réseau neuronal dans server.py
==============================================================
Place connect4_model.pt et connect4_model_info.json dans le
même dossier que ce fichier.
"""

import os
import json
import math
import torch
import torch.nn as nn
from typing import Optional, List

ROWS   = 9
COLS   = 9
RED    = "R"
YELLOW = "Y"
EMPTY  = "."


# ════════════════════════════════════════════
# ARCHITECTURE (identique à train_model.py)
# ════════════════════════════════════════════

class ResBlock(nn.Module):
    def __init__(self, ch):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(ch, ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(ch), nn.ReLU(inplace=True),
            nn.Conv2d(ch, ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(ch),
        )
        self.relu = nn.ReLU(inplace=True)
    def forward(self, x): return self.relu(x + self.net(x))


class Connect4Net(nn.Module):
    def __init__(self, rows=ROWS, cols=COLS, in_ch=3, filters=128, blocks=6):
        super().__init__()
        self.rows, self.cols = rows, cols
        self.stem = nn.Sequential(
            nn.Conv2d(in_ch, filters, 3, padding=1, bias=False),
            nn.BatchNorm2d(filters), nn.ReLU(inplace=True),
        )
        self.body = nn.Sequential(*[ResBlock(filters) for _ in range(blocks)])
        self.policy_head = nn.Sequential(
            nn.Conv2d(filters, 32, 1, bias=False), nn.BatchNorm2d(32), nn.ReLU(inplace=True),
            nn.Flatten(), nn.Linear(32 * rows * cols, cols),
        )
        self.value_head = nn.Sequential(
            nn.Conv2d(filters, 1, 1, bias=False), nn.BatchNorm2d(1), nn.ReLU(inplace=True),
            nn.Flatten(), nn.Linear(rows * cols, 64), nn.ReLU(inplace=True),
            nn.Linear(64, 1), nn.Tanh(),
        )
    def forward(self, x):
        t = self.body(self.stem(x))
        return self.policy_head(t), self.value_head(t)


# ════════════════════════════════════════════
# MINIMAX LÉGER (pour sécuriser les coups)
# ════════════════════════════════════════════

def _mm_drop(board, col, color, rows):
    for r in range(rows - 1, -1, -1):
        if board[r][col] == EMPTY:
            board[r][col] = color
            return r
    return -1

def _mm_undo(board, row, col): board[row][col] = EMPTY

def _mm_win(board, color, rows, cols):
    for r in range(rows):
        for c in range(cols):
            if board[r][c] != color: continue
            for dr, dc in [(0,1),(1,0),(1,1),(1,-1)]:
                cnt = 0
                for k in range(4):
                    nr, nc = r+k*dr, c+k*dc
                    if 0<=nr<rows and 0<=nc<cols and board[nr][nc]==color: cnt+=1
                    else: break
                if cnt == 4: return True
    return False

def _mm_valid(board, cols):
    return [c for c in range(cols) if board[0][c] == EMPTY]

def _mm_threats(board, color, rows, cols):
    count = 0
    for c in range(cols):
        r = _mm_drop(board, c, color, rows)
        if r >= 0:
            if _mm_win(board, color, rows, cols): count += 1
            _mm_undo(board, r, c)
    return count

def _minimax(board, depth, alpha, beta, maxing, ai, rows, cols):
    opp = YELLOW if ai == RED else RED
    valid = _mm_valid(board, cols)
    if _mm_win(board, ai,  rows, cols): return  10_000_000 + depth
    if _mm_win(board, opp, rows, cols): return -10_000_000 - depth
    if not valid or depth == 0: return 0
    center = cols // 2
    ordered = sorted(valid, key=lambda c: abs(c - center))
    if maxing:
        val = -math.inf
        for c in ordered:
            r = _mm_drop(board, c, ai, rows)
            if r < 0: continue
            score = _minimax(board, depth-1, alpha, beta, False, ai, rows, cols)
            _mm_undo(board, r, c)
            val = max(val, score); alpha = max(alpha, val)
            if alpha >= beta: break
        return val
    else:
        val = math.inf
        for c in ordered:
            r = _mm_drop(board, c, opp, rows)
            if r < 0: continue
            score = _minimax(board, depth-1, alpha, beta, True, ai, rows, cols)
            _mm_undo(board, r, c)
            val = min(val, score); beta = min(beta, val)
            if alpha >= beta: break
        return val


# ════════════════════════════════════════════
# CLASSE PRINCIPALE
# ════════════════════════════════════════════

class NeuralAI:
    """
    IA hybride : Réseau neuronal + Minimax de sécurité.
    S'intègre dans server.py via ai_choose_column_from_game_neural().
    """
    _instance = None  # Singleton pour éviter de recharger le modèle

    def __init__(self, model_path: str, info_path: Optional[str] = None):
        self.device = torch.device("cpu")

        # Charger les infos du modèle
        info = {"rows": ROWS, "cols": COLS, "in_channels": 3,
                "num_filters": 128, "num_res_blocks": 6}
        if info_path and os.path.exists(info_path):
            with open(info_path, encoding="utf-8") as f:
                info.update(json.load(f))

        self.rows = info.get("rows", ROWS)
        self.cols = info.get("cols", COLS)

        self.model = Connect4Net(
            rows=self.rows, cols=self.cols,
            in_ch=info.get("in_channels", 3),
            filters=info.get("num_filters", 128),
            blocks=info.get("num_res_blocks", 6),
        ).to(self.device)

        self.model.load_state_dict(
            torch.load(model_path, map_location=self.device)
        )
        self.model.eval()
        print(f"✅  NeuralAI chargée — {info.get('epochs_done','?')} epochs  "
              f"(filters={info.get('num_filters')}, blocks={info.get('num_res_blocks')})")

    @classmethod
    def get_instance(cls) -> Optional["NeuralAI"]:
        """Retourne le singleton, le charge si nécessaire."""
        if cls._instance is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            model_path = os.path.join(script_dir, "connect4_model.pt")
            info_path  = os.path.join(script_dir, "connect4_model_info.json")
            if not os.path.exists(model_path):
                print(f"⚠️  connect4_model.pt introuvable dans {script_dir}")
                return None
            try:
                cls._instance = cls(model_path, info_path)
            except Exception as e:
                print(f"⚠️  Impossible de charger NeuralAI : {e}")
                return None
        return cls._instance

    def _board_to_tensor(self, board: list, turn: str) -> torch.Tensor:
        rows = len(board)
        cols = len(board[0]) if board else self.cols
        r_p = torch.zeros(rows, cols)
        y_p = torch.zeros(rows, cols)
        for i in range(rows):
            for j in range(cols):
                if board[i][j] == RED:    r_p[i, j] = 1.0
                elif board[i][j] == YELLOW: y_p[i, j] = 1.0
        me  = r_p if turn == RED else y_p
        opp = y_p if turn == RED else r_p
        return torch.stack([me, opp, torch.ones(rows, cols)], 0).unsqueeze(0)

    def choose_column(self, board: list, turn: str,
                      valid_cols: Optional[List[int]] = None) -> int:
        """
        Choisit la meilleure colonne.
        Logique :
          1. Victoire immédiate           → joue
          2. Blocage adverse immédiat     → bloque
          3. Double menace adverse        → minimax depth=4
          4. Réseau neuronal propose      → vérifie si suicidaire
          5. Si suicidaire                → minimax depth=4 corrige
        """
        rows = len(board)
        cols = len(board[0]) if board else self.cols

        if valid_cols is None:
            valid_cols = [c for c in range(cols) if board[0][c] == EMPTY]
        if not valid_cols:
            return 0
        if len(valid_cols) == 1:
            return valid_cols[0]

        opp    = YELLOW if turn == RED else RED
        center = cols // 2
        ordered = sorted(valid_cols, key=lambda c: abs(c - center))

        # 1. Victoire immédiate
        for c in ordered:
            r = _mm_drop(board, c, turn, rows)
            if r >= 0:
                if _mm_win(board, turn, rows, cols):
                    _mm_undo(board, r, c)
                    return c
                _mm_undo(board, r, c)

        # 2. Bloquer victoire adverse
        for c in ordered:
            r = _mm_drop(board, c, opp, rows)
            if r >= 0:
                if _mm_win(board, opp, rows, cols):
                    _mm_undo(board, r, c)
                    return c
                _mm_undo(board, r, c)

        # 3. Double menace adverse → minimax
        b_copy = [row[:] for row in board]
        if _mm_threats(b_copy, opp, rows, cols) >= 2:
            return self._minimax_col(board, turn, rows, cols, ordered, depth=4)

        # 4. Réseau neuronal
        with torch.no_grad():
            logits, _ = self.model(self._board_to_tensor(board, turn).to(self.device))
        logits = logits.squeeze(0).cpu()
        mask = torch.full((cols,), float("-inf"))
        for c in valid_cols: mask[c] = logits[c]
        neural_col = int(mask.argmax().item())

        # 5. Vérifier si suicidaire
        b2 = [row[:] for row in board]
        r2 = _mm_drop(b2, neural_col, turn, rows)
        suicidaire = False
        if r2 >= 0:
            for oc in _mm_valid(b2, cols):
                rr = _mm_drop(b2, oc, opp, rows)
                if rr >= 0:
                    if _mm_win(b2, opp, rows, cols):
                        suicidaire = True
                        _mm_undo(b2, rr, oc); break
                    _mm_undo(b2, rr, oc)
            _mm_undo(b2, r2, neural_col)

        if suicidaire:
            return self._minimax_col(board, turn, rows, cols, ordered, depth=4)

        return neural_col

    def _minimax_col(self, board, turn, rows, cols, ordered, depth=4):
        b = [row[:] for row in board]
        best_col = ordered[0]; best_score = -math.inf
        for c in ordered:
            r = _mm_drop(b, c, turn, rows)
            if r < 0: continue
            score = _minimax(b, depth-1, -math.inf, math.inf, False, turn, rows, cols)
            _mm_undo(b, r, c)
            if score > best_score: best_score = score; best_col = c
        return best_col


# ════════════════════════════════════════════
# FONCTION D'INTERFACE POUR server.py
# ════════════════════════════════════════════

def ai_choose_column_neural(game) -> int:
    """
    Point d'entrée pour server.py.
    Utilise le singleton NeuralAI.

    Dans server.py, remplace :
        best_col = ai_choose_column_from_game(game, ...)
    Par :
        from neural_ai import ai_choose_column_neural
        best_col = ai_choose_column_neural(game)
    """
    ai = NeuralAI.get_instance()
    if ai is None:
        # Fallback : minimax si modèle pas disponible
        from ai_engine import ai_choose_column_from_game
        return ai_choose_column_from_game(game, db_available=False, robot_depth=5)

    board      = game.board
    turn       = game.current_turn
    valid_cols = game.valid_columns()

    return ai.choose_column(board, turn, valid_cols)
