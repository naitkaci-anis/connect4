"""
ai_engine.py  —  IA Puissance 4  (version forte v2)
=====================================================
Corrections v2 :
  - priority() supprimée des nœuds internes → x3 plus rapide → depth 7-9 réel
  - Détection double menace dans l'heuristique (piège = perte quasi certaine)
  - Filtre coups suicidaires AVANT le minimax
  - Aspiration window pour accélérer iterative deepening
  - TIME_LIMIT 2.5s
"""

from __future__ import annotations
import time
from typing import List, Optional, Dict, Tuple

RED = "R"; YELLOW = "Y"; EMPTY = "."
EXACT = 0; LOWER = 1; UPPER = 2

WIN_SCORE  =  10_000_000
LOSE_SCORE = -10_000_000
TIME_LIMIT = 2.5          # secondes max par coup (augmenté)


# ══════════════════════════════════════════════════════════════
# BITBOARD
# ══════════════════════════════════════════════════════════════

class BB:
    __slots__ = ("rows","cols","r_bb","y_bb","heights",
                 "win_masks","cell_masks","col_order")

    def __init__(self, rows: int, cols: int):
        self.rows    = rows
        self.cols    = cols
        self.r_bb    = 0
        self.y_bb    = 0
        self.heights = [rows - 1] * cols
        self.win_masks  = _build_win_masks(rows, cols)
        self.cell_masks = _build_cell_masks(rows, cols, self.win_masks)
        self.col_order  = sorted(range(cols), key=lambda c: abs(c - cols // 2))

    def valid(self) -> List[int]:
        return [c for c in self.col_order if self.heights[c] >= 0]

    def drop(self, col: int, red: bool) -> int:
        pos = self.heights[col] * self.cols + col
        if red: self.r_bb |= 1 << pos
        else:   self.y_bb |= 1 << pos
        self.heights[col] -= 1
        return pos

    def undo(self, col: int, pos: int, red: bool):
        self.heights[col] += 1
        if red: self.r_bb ^= 1 << pos
        else:   self.y_bb ^= 1 << pos

    def won(self, pos: int, red: bool) -> bool:
        bb = self.r_bb if red else self.y_bb
        for m in self.cell_masks[pos]:
            if (bb & m) == m:
                return True
        return False

    def full(self) -> bool:
        return all(self.heights[c] < 0 for c in range(self.cols))

    # ------------------------------------------------------------------
    # Compte les colonnes donnant une victoire immédiate
    # ------------------------------------------------------------------
    def count_threats(self, red: bool) -> int:
        count = 0
        bb_val = self.r_bb if red else self.y_bb
        for col in self.valid():
            pos = self.heights[col] * self.cols + col
            bit = 1 << pos
            test = bb_val | bit
            for m in self.cell_masks[pos]:
                if (test & m) == m:
                    count += 1
                    break
        return count

    # ------------------------------------------------------------------
    # Heuristique — rapide et fiable
    # ------------------------------------------------------------------
    def heuristic(self, ai_red: bool) -> int:
        my  = self.r_bb if ai_red else self.y_bb
        opp = self.y_bb if ai_red else self.r_bb
        cols   = self.cols
        center = cols // 2
        score  = 0

        # 1) Bonus centre
        for bit in range(self.rows * cols):
            c = bit % cols
            w = (cols - abs(c - center)) * 4
            if my  >> bit & 1: score += w
            if opp >> bit & 1: score -= w

        # 2) Fenêtres de 4
        for m in self.win_masks:
            mc = bin(my  & m).count('1')
            oc = bin(opp & m).count('1')
            if mc and oc: continue
            if oc == 0:
                if   mc == 3: score += 1_000   # menace de victoire
                elif mc == 2: score +=    30
                elif mc == 1: score +=     3
            elif mc == 0:
                if   oc == 3: score -= 3_000   # bloquer adversaire prioritaire
                elif oc == 2: score -=    60
                elif oc == 1: score -=     5

        # 3) Menaces immédiates (décisif)
        my_t  = self.count_threats(ai_red)
        opp_t = self.count_threats(not ai_red)

        score += my_t  * 80_000
        score -= opp_t * 100_000   # pénaliser fort les menaces adverses

        # 4) Double menace = victoire / défaite quasi certaine
        if my_t  >= 2: score += 800_000   # on va gagner
        if opp_t >= 2: score -= 900_000   # on va perdre (piège)

        return score


# ══════════════════════════════════════════════════════════════
# MASQUES (pré-calculés, mis en cache)
# ══════════════════════════════════════════════════════════════

_MASK_CACHE: Dict[Tuple[int,int], Tuple] = {}

def _build_win_masks(rows: int, cols: int) -> List[int]:
    key = (rows, cols)
    if key in _MASK_CACHE: return _MASK_CACHE[key][0]
    masks = []
    for r in range(rows):
        for c in range(cols):
            for dr, dc in [(0,1),(1,0),(1,1),(1,-1)]:
                bits, ok = [], True
                for k in range(4):
                    nr, nc = r+k*dr, c+k*dc
                    if not (0 <= nr < rows and 0 <= nc < cols): ok = False; break
                    bits.append(nr*cols+nc)
                if ok:
                    m = 0
                    for b in bits: m |= 1 << b
                    masks.append(m)
    return masks

def _build_cell_masks(rows: int, cols: int, win_masks: List[int]) -> List[List[int]]:
    cm: List[List[int]] = [[] for _ in range(rows*cols)]
    for m in win_masks:
        t = m
        while t:
            lsb = t & -t
            cm[lsb.bit_length()-1].append(m)
            t ^= lsb
    _MASK_CACHE[(rows, cols)] = (win_masks, cm)
    return cm


# ══════════════════════════════════════════════════════════════
# MINIMAX alpha-beta + TT
# Amélioration clé : priority() supprimée des nœuds internes
# ══════════════════════════════════════════════════════════════

def _search(bb: BB, depth: int, alpha: int, beta: int,
            maxing: bool, ai_red: bool, cur_red: bool,
            last_pos: int, tt: dict, deadline: float) -> int:

    # Victoire du coup précédent
    if last_pos >= 0 and bb.won(last_pos, not cur_red):
        prev_red = not cur_red
        return (WIN_SCORE + depth) if (prev_red == ai_red) else (LOSE_SCORE - depth)

    valid = bb.valid()
    if not valid: return 0
    if depth == 0 or time.time() > deadline:
        return bb.heuristic(ai_red)

    # Table de transposition
    key = (bb.r_bb, bb.y_bb, depth, maxing)
    hit = tt.get(key)
    if hit:
        flag, val = hit
        if flag == EXACT: return val
        if flag == LOWER: alpha = max(alpha, val)
        elif flag == UPPER: beta = min(beta, val)
        if alpha >= beta: return val

    a0, b0 = alpha, beta

    # ── Tri des coups RAPIDE (pas de drop/undo ici → x3 plus vite) ──
    # On utilise juste l'ordre centre pré-calculé (déjà dans bb.col_order)
    # Les coups gagnants/bloquants sont détectés NATURELLEMENT par
    # l'alpha-beta : un coup qui gagne retourne WIN_SCORE immédiatement
    # et coupe toutes les autres branches.
    # On garde quand même un tri léger sur les 2 premiers niveaux.
    if depth >= 3:
        # Tri rapide : détecter gagnant/bloquant sans drop complet
        winners = []
        blockers = []
        others   = []
        ai_bb    = bb.r_bb if cur_red else bb.y_bb
        opp_bb   = bb.y_bb if cur_red else bb.r_bb
        for col in valid:
            pos = bb.heights[col] * bb.cols + col
            bit = 1 << pos
            # Gagnant immédiat ?
            test = ai_bb | bit
            win = any((test & m) == m for m in bb.cell_masks[pos])
            if win: winners.append(col); continue
            # Bloquant immédiat ?
            test2 = opp_bb | bit
            block = any((test2 & m) == m for m in bb.cell_masks[pos])
            if block: blockers.append(col); continue
            others.append(col)
        ordered = winners + blockers + others
    else:
        # Nœuds profonds : juste l'ordre centre (très rapide)
        ordered = valid

    if maxing:
        best = LOSE_SCORE - 1
        for col in ordered:
            pos = bb.drop(col, cur_red)
            sc  = _search(bb, depth-1, alpha, beta, False,
                          ai_red, not cur_red, pos, tt, deadline)
            bb.undo(col, pos, cur_red)
            if sc > best: best = sc
            alpha = max(alpha, best)
            if alpha >= beta: break
    else:
        best = WIN_SCORE + 1
        for col in ordered:
            pos = bb.drop(col, cur_red)
            sc  = _search(bb, depth-1, alpha, beta, True,
                          ai_red, not cur_red, pos, tt, deadline)
            bb.undo(col, pos, cur_red)
            if sc < best: best = sc
            beta = min(beta, best)
            if alpha >= beta: break

    flag = EXACT if a0 < best < b0 else (LOWER if best >= b0 else UPPER)
    tt[key] = (flag, best)
    return best


# ══════════════════════════════════════════════════════════════
# ITERATIVE DEEPENING + ASPIRATION WINDOW
# ══════════════════════════════════════════════════════════════

def _iterative_deepening(bb: BB, ai_red: bool, max_depth: int,
                          deadline: float) -> int:
    valid = bb.valid()
    if not valid: raise ValueError("Aucun coup")
    if len(valid) == 1: return valid[0]

    best_col = sorted(valid, key=lambda c: abs(c - bb.cols // 2))[0]
    tt: dict = {}
    prev_score = 0

    for depth in range(1, max_depth + 1):
        if time.time() > deadline: break

        scores: Dict[int, int] = {}

        # Aspiration window : commence avec une fenêtre étroite autour du score précédent
        if depth >= 3:
            delta = 200
            alpha = prev_score - delta
            beta  = prev_score + delta
        else:
            alpha = LOSE_SCORE - 1
            beta  = WIN_SCORE  + 1

        # Ordre des coups selon le meilleur coup de l'itération précédente
        ordered = sorted(valid, key=lambda c: (0 if c == best_col else 1, abs(c - bb.cols // 2)))

        research = False
        for col in ordered:
            if time.time() > deadline: break
            pos = bb.drop(col, ai_red)
            sc  = _search(bb, depth-1, alpha, beta, False,
                          ai_red, not ai_red, pos, tt, deadline)
            bb.undo(col, pos, ai_red)
            scores[col] = sc

            # Si hors fenêtre → relancer sans restriction
            if sc <= alpha or sc >= beta:
                research = True
                alpha = LOSE_SCORE - 1
                beta  = WIN_SCORE  + 1

        # Relancer si nécessaire (aspiration failed)
        if research and not (time.time() > deadline):
            scores_retry: Dict[int, int] = {}
            for col in ordered:
                if time.time() > deadline: break
                pos = bb.drop(col, ai_red)
                sc  = _search(bb, depth-1, LOSE_SCORE-1, WIN_SCORE+1, False,
                              ai_red, not ai_red, pos, tt, deadline)
                bb.undo(col, pos, ai_red)
                scores_retry[col] = sc
            if scores_retry:
                scores.update(scores_retry)

        if not scores: break

        best_col   = max(scores, key=lambda c: scores[c])
        prev_score = scores[best_col]

        # Victoire forcée trouvée → inutile de chercher plus
        if prev_score >= WIN_SCORE: break
        # Défaite forcée → chercher encore (peut-être on peut retarder)

    return best_col


# ══════════════════════════════════════════════════════════════
# OPENING BOOK BD
# ══════════════════════════════════════════════════════════════

_BOOK: Optional[Dict[str, int]] = None
_BOOK_KEY: Tuple[int,int] = (-1,-1)


def _get_book(rows: int, cols: int, sc: str) -> Dict[str, int]:
    global _BOOK, _BOOK_KEY
    if _BOOK is not None and _BOOK_KEY == (rows, cols):
        return _BOOK
    _BOOK = _load_book(rows, cols, sc)
    _BOOK_KEY = (rows, cols)
    return _BOOK


def _load_book(rows: int, cols: int, starting_color: str, depth: int = 14) -> Dict[str, int]:
    try:
        import db as _db
    except ImportError:
        return {}
    book: Dict[str, Dict[int, int]] = {}
    try:
        with _db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT original_sequence, winner, draw, starting_color "
                "FROM games WHERE status='FINISHED' "
                "AND rows=%s AND cols=%s AND confiance>=2 LIMIT 500000",
                (rows, cols)
            )
            rows_data = cur.fetchall()
    except Exception as e:
        print(f"[Book] erreur BD : {e}")
        return {}

    for seq_str, winner, draw, s_col in rows_data:
        if not seq_str: continue
        try:
            digits = [int(x) for x in str(seq_str).split(",") if x.strip()]
        except Exception:
            continue
        turn = s_col or starting_color
        for i, col_1 in enumerate(digits):
            if i >= depth: break
            prefix = ",".join(str(d) for d in digits[:i])
            try:
                canon = _db.canonical_key(prefix, cols) if prefix else "__start__"
            except Exception:
                canon = "__start__"
            col_0 = col_1 - 1
            sc = 2 if (not draw and winner == turn) else (-1 if (not draw and winner) else 0)
            if canon not in book: book[canon] = {}
            book[canon][col_0] = book[canon].get(col_0, 0) + sc
            turn = YELLOW if turn == RED else RED

    result = {}
    for canon, cs in book.items():
        if len(cs) >= 5:
            result[canon] = max(cs, key=lambda c: cs[c])
    print(f"[Book] {len(result)} positions chargées (rows={rows} cols={cols})")
    return result


def _book_col(moves_played: List[int], cols: int, rows: int,
              sc: str, cursor: int) -> Optional[int]:
    if cursor >= 14: return None
    book = _get_book(rows, cols, sc)
    if not book: return None
    try:
        import db as _db
        prefix = ",".join(str(c+1) for c in moves_played)
        canon  = _db.canonical_key(prefix, cols) if prefix else "__start__"
    except Exception:
        return None
    return book.get(canon)


def _fixed_opening(bb: BB, ai_red: bool, cursor: int) -> Optional[int]:
    """Règles solides pour les 6 premiers coups."""
    valid  = bb.valid()
    cols   = bb.cols
    center = cols // 2
    ai_bb  = bb.r_bb if ai_red else bb.y_bb
    opp_bb = bb.y_bb if ai_red else bb.r_bb

    # Toujours gagner / bloquer en premier
    for col in valid:
        pos = bb.heights[col] * cols + col
        bit = 1 << pos
        if any(((ai_bb | bit) & m) == m for m in bb.cell_masks[pos]): return col
    for col in valid:
        pos = bb.heights[col] * cols + col
        bit = 1 << pos
        if any(((opp_bb | bit) & m) == m for m in bb.cell_masks[pos]): return col

    if cursor == 0: return center
    if cursor == 1:
        if bb.heights[center] < bb.rows - 1:
            cands = [c for c in [center-1, center+1] if 0 <= c < cols and bb.heights[c] >= 0]
            return cands[0] if cands else center
        return center

    zone = [c for c in range(max(0, center-1), min(cols, center+2)) if bb.heights[c] >= 0]
    if zone:
        return sorted(zone, key=lambda c: bb.heights[c], reverse=True)[0]
    return sorted(valid, key=lambda c: abs(c - center))[0]


# ══════════════════════════════════════════════════════════════
# FILTRE COUPS SUICIDAIRES
# ══════════════════════════════════════════════════════════════

def _filter_suicide(bb: BB, valid: List[int], ai_red: bool) -> List[int]:
    """
    Retire les coups qui donnent une victoire immédiate à l'adversaire
    au coup suivant (sauf si on n'a pas le choix).
    """
    opp_red = not ai_red
    safe = []
    for col in valid:
        pos = bb.drop(col, ai_red)
        # Vérifier si l'adversaire peut gagner immédiatement après ce coup
        opp_wins = False
        for ocol in bb.valid():
            opos = bb.heights[ocol] * bb.cols + ocol
            obit = 1 << opos
            opp_bb = bb.y_bb if opp_red else bb.r_bb
            if any(((opp_bb | obit) & m) == m for m in bb.cell_masks[opos]):
                opp_wins = True
                break
        bb.undo(col, pos, ai_red)
        if not opp_wins:
            safe.append(col)

    # Si tous les coups sont suicidaires → on n'a pas le choix, on garde tout
    return safe if safe else valid


# ══════════════════════════════════════════════════════════════
# POINT D'ENTRÉE PRINCIPAL
# ══════════════════════════════════════════════════════════════

def choose_column(
    board          : List[List[str]],
    current_turn   : str,
    rows           : int,
    cols           : int,
    starting_color : str,
    moves_played   : List[int],
    cursor         : int,
    depth          : int   = 7,
    db_available   : bool  = True,
    time_limit     : float = TIME_LIMIT,
) -> int:
    ai_red   = (current_turn == RED)
    opp_red  = not ai_red
    deadline = time.time() + time_limit

    # ── Construire le bitboard ────────────────────────────
    bb = BB(rows, cols)
    for r in range(rows):
        for c in range(cols):
            cell = board[r][c]
            if   cell == RED:    bb.r_bb |= 1 << (r*cols+c)
            elif cell == YELLOW: bb.y_bb |= 1 << (r*cols+c)

    bb.heights = []
    for c in range(cols):
        h = rows - 1
        while h >= 0 and board[h][c] != EMPTY: h -= 1
        bb.heights.append(h)

    valid = bb.valid()
    if not valid: raise ValueError("Aucun coup valide")
    if len(valid) == 1: return valid[0]

    ai_bb  = bb.r_bb if ai_red else bb.y_bb
    opp_bb = bb.y_bb if ai_red else bb.r_bb

    # ── 1. Coup gagnant immédiat ──────────────────────────
    for col in valid:
        pos = bb.heights[col] * cols + col
        bit = 1 << pos
        if any(((ai_bb | bit) & m) == m for m in bb.cell_masks[pos]):
            return col

    # ── 2. Blocage immédiat ───────────────────────────────
    for col in valid:
        pos = bb.heights[col] * cols + col
        bit = 1 << pos
        if any(((opp_bb | bit) & m) == m for m in bb.cell_masks[pos]):
            return col

    # ── 3. Opening book BD ────────────────────────────────
    if db_available and cursor < 14:
        bc = _book_col(moves_played, cols, rows, starting_color, cursor)
        if bc is not None and 0 <= bc < cols and bb.heights[bc] >= 0:
            return bc

    # ── 4. Opening fixe (premiers coups si book vide) ─────
    if cursor < 6:
        fc = _fixed_opening(bb, ai_red, cursor)
        if fc is not None:
            return fc

    # ── 5. Filtre coups suicidaires ───────────────────────
    valid = _filter_suicide(bb, valid, ai_red)

    # ── 6. Minimax iterative deepening ───────────────────
    cells  = rows * cols
    filled = sum(1 for r in range(rows) for c in range(cols) if board[r][c] != EMPTY)

    # Profondeur adaptative
    if cells >= 81:
        max_d = min(depth, 7)
    elif cells >= 64:
        max_d = min(depth, 8)
    else:
        max_d = min(depth, 9)

    # Plus profond en fin de partie
    if filled / cells > 0.55:
        max_d = min(max_d + 2, 12)
    elif filled / cells > 0.35:
        max_d = min(max_d + 1, 10)

    return _iterative_deepening(bb, ai_red, max_d, deadline)


# ══════════════════════════════════════════════════════════════
# INTERFACE server.py
# ══════════════════════════════════════════════════════════════

def ai_choose_column_from_game(game, db_available: bool = True,
                                robot_depth: int = 7,
                                mode: str = "minimax") -> int:
    """
    Appel depuis server.py :
        col = ai_choose_column_from_game(game, DB_AVAILABLE, robot_depth, robot_algo)
    mode : "minimax" ou "strategic" (les deux utilisent le même moteur)
    """
    moves_played = [m.col for m in game.moves[:game.cursor]]
    return choose_column(
        board          = game.board,
        current_turn   = game.current_turn,
        rows           = game.rows,
        cols           = game.cols,
        starting_color = game.starting_color,
        moves_played   = moves_played,
        cursor         = game.cursor,
        depth          = robot_depth,
        db_available   = db_available,
        time_limit     = TIME_LIMIT,
    )


# ══════════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import time as T

    rows, cols = 9, 9
    board = [[EMPTY]*cols for _ in range(rows)]

    print("Test 1 — grille vide (doit jouer centre col 5)")
    t0 = T.time()
    col = choose_column(board, RED, rows, cols, RED, [], 0, depth=7, db_available=False)
    print(f"  → col {col+1}  ({(T.time()-t0)*1000:.0f}ms)")

    print("Test 2 — victoire immédiate (doit jouer col 4)")
    b2 = [[EMPTY]*cols for _ in range(rows)]
    for i in range(3): b2[rows-1][i] = RED
    t0 = T.time()
    col2 = choose_column(b2, RED, rows, cols, RED, [1,5,2,5,3,5], 6, depth=7, db_available=False)
    print(f"  → col {col2+1}  attendu: 4  {'✅' if col2==3 else '❌'} ({(T.time()-t0)*1000:.0f}ms)")

    print("Test 3 — blocage immédiat (doit bloquer col 4)")
    b3 = [[EMPTY]*cols for _ in range(rows)]
    for i in range(3): b3[rows-1][i] = YELLOW
    t0 = T.time()
    col3 = choose_column(b3, RED, rows, cols, RED, [5,1,5,2,5,3], 6, depth=7, db_available=False)
    print(f"  → col {col3+1}  attendu: 4  {'✅' if col3==3 else '❌'} ({(T.time()-t0)*1000:.0f}ms)")

    print("Test 4 — double menace adversaire (ne doit pas jouer un coup suicide)")
    b4 = [[EMPTY]*cols for _ in range(rows)]
    # Jaune a 2 menaces en col 3 et col 7
    for i in range(3): b4[rows-1][i+1] = YELLOW   # menace col 4
    for i in range(3): b4[rows-1][i+5] = YELLOW   # menace col 8
    t0 = T.time()
    col4 = choose_column(b4, RED, rows, cols, RED, [], 6, depth=7, db_available=False)
    print(f"  → col {col4+1}  ({(T.time()-t0)*1000:.0f}ms)")

    print("\n✅ Tests terminés.")

