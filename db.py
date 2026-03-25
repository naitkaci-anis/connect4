import os
import re
from typing import List, Optional, Tuple, Dict, Any

import psycopg2
import psycopg2.extras

RED = "R"
YELLOW = "Y"


# ============================================================
# Connexion
# ============================================================

def get_conn():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL n'est pas défini.\n"
            'PowerShell:\n$env:DATABASE_URL="postgresql://postgres:TON_MDP@localhost:5432/connect4"'
        )
    return psycopg2.connect(url)


def _dict_cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


# ============================================================
# Séquences (support cols > 9)
# ============================================================

def _parse_seq(seq: str, cols: int) -> List[int]:
    seq = (seq or "").strip()
    if not seq:
        return []

    if "," in seq:
        out = [int(x.strip()) for x in seq.split(",") if x.strip()]
    else:
        if cols > 9:
            raise ValueError("cols>9 => utilise format CSV '1,10,3'")
        out = [int(ch) for ch in seq]

    for d in out:
        if d < 1 or d > cols:
            raise ValueError(f"col {d} hors [1..{cols}]")

    return out


def normalize_sequence(seq: str, cols: int) -> str:
    return ",".join(str(d) for d in _parse_seq(seq, cols))


def mirror_sequence(seq: str, cols: int) -> str:
    cols_list = _parse_seq(seq, cols)
    return ",".join(str((cols + 1) - d) for d in cols_list)


def canonical_key(seq: str, cols: int) -> str:
    a = normalize_sequence(seq, cols)
    b = mirror_sequence(a, cols)
    return min(a, b)


def parse_sequence_from_filename(path: str) -> str:
    name = os.path.basename(path)
    m = re.match(r"^([0-9]+)\.txt$", name)
    if not m:
        raise ValueError("Nom invalide. Exemple: 3131313.txt")
    return m.group(1)


# ============================================================
# Simulation depuis une séquence
# ============================================================

def _simulate_moves_from_sequence(
    seq: str, rows: int, cols: int, starting_color: str
) -> List[Dict[str, Any]]:
    """
    Transforme une séquence ex: "3,1,3,1" en liste de moves avec
    ply, col, row, color
    """
    seq_norm = normalize_sequence(seq, cols)
    digits = _parse_seq(seq_norm, cols)

    board = [[None for _ in range(cols)] for _ in range(rows)]
    moves: List[Dict[str, Any]] = []

    turn = starting_color
    for ply, d in enumerate(digits, start=1):
        col = d - 1

        row = rows - 1
        while row >= 0 and board[row][col] is not None:
            row -= 1

        if row < 0:
            raise ValueError(f"Colonne pleine au coup {ply} (col={d})")

        board[row][col] = turn
        moves.append({
            "ply": ply,
            "col": col,
            "row": row,
            "color": turn,
        })

        turn = YELLOW if turn == RED else RED

    return moves


# ============================================================
# LIST / GET
# ============================================================

def list_games(limit: int = 200) -> List[Dict[str, Any]]:
    with get_conn() as conn, _dict_cur(conn) as cur:
        cur.execute(
            """
            SELECT id, rows, cols, starting_color, status, winner, draw,
                   original_sequence, canonical_key, source_filename, created_at,
                   confiance
            FROM games
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        )
        return list(cur.fetchall())


def list_in_progress(limit: int = 100) -> List[Dict[str, Any]]:
    with get_conn() as conn, _dict_cur(conn) as cur:
        cur.execute(
            """
            SELECT id, rows, cols, starting_color, status, winner, draw,
                   original_sequence, canonical_key, source_filename, created_at,
                   confiance
            FROM games
            WHERE status='IN_PROGRESS'
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        )
        return list(cur.fetchall())


def get_latest_in_progress() -> Optional[Dict[str, Any]]:
    with get_conn() as conn, _dict_cur(conn) as cur:
        cur.execute(
            """
            SELECT id, rows, cols, starting_color, status, winner, draw,
                   original_sequence, canonical_key, source_filename, created_at,
                   confiance
            FROM games
            WHERE status='IN_PROGRESS'
            ORDER BY id DESC
            LIMIT 1
            """
        )
        r = cur.fetchone()
        return dict(r) if r else None


def get_game_with_moves(game_id: int) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    with get_conn() as conn, _dict_cur(conn) as cur:
        cur.execute("SELECT * FROM games WHERE id=%s", (game_id,))
        g = cur.fetchone()
        if not g:
            raise ValueError("Game introuvable")

        cur.execute(
            """
            SELECT ply, col, row, color, played_at
            FROM moves
            WHERE game_id=%s
            ORDER BY ply ASC
            """,
            (game_id,),
        )
        moves = list(cur.fetchall())
        return dict(g), moves


def get_game_for_app(game_id: int) -> Dict[str, Any]:
    g, moves = get_game_with_moves(game_id)
    return {
        "id": g["id"],
        "rows": int(g["rows"]),
        "cols": int(g["cols"]),
        "starting_color": g["starting_color"],
        "status": g["status"],
        "winner": g["winner"],
        "draw": bool(g["draw"]),
        "original_sequence": g.get("original_sequence") or "",
        "canonical_key": g.get("canonical_key") or "",
        "source_filename": g.get("source_filename"),
        "confiance": int(g.get("confiance") or 1),
        "moves": [
            {
                "ply": int(m["ply"]),
                "col": int(m["col"]),
                "row": int(m["row"]),
                "color": m["color"],
            }
            for m in moves
        ],
    }


def list_symmetries(game_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    g, _ = get_game_with_moves(game_id)
    canon = str(g.get("canonical_key") or "")
    if not canon:
        return []

    with get_conn() as conn, _dict_cur(conn) as cur:
        cur.execute(
            """
            SELECT id, status, winner, draw,
                   original_sequence, canonical_key, source_filename, created_at,
                   confiance
            FROM games
            WHERE rows=%s AND cols=%s AND starting_color=%s AND canonical_key=%s
            ORDER BY id DESC
            LIMIT %s
            """,
            (g["rows"], g["cols"], g["starting_color"], canon, limit),
        )
        return list(cur.fetchall())


# ============================================================
# Fonctions utiles pour IA basée sur la BD
# ============================================================

def get_position_candidates(
    prefix_seq: str,
    rows: int,
    cols: int,
    starting_color: str,
    limit: int = 5000,
    min_confiance: int = 1,
) -> List[Dict[str, Any]]:
    """
    Retourne les parties FINISHED dont la séquence commence par prefix_seq
    ou par son miroir.
    """
    prefix_norm = normalize_sequence(prefix_seq, cols) if prefix_seq else ""
    prefix_mirror = mirror_sequence(prefix_norm, cols) if prefix_norm else ""

    with get_conn() as conn, _dict_cur(conn) as cur:
        if prefix_norm:
            cur.execute(
                """
                SELECT id, rows, cols, starting_color, status, winner, draw,
                       original_sequence, canonical_key, source_filename, created_at,
                       confiance
                FROM games
                WHERE rows=%s
                  AND cols=%s
                  AND starting_color=%s
                  AND status='FINISHED'
                  AND confiance >= %s
                  AND original_sequence IS NOT NULL
                  AND (
                        original_sequence = %s
                     OR original_sequence LIKE %s
                     OR original_sequence = %s
                     OR original_sequence LIKE %s
                  )
                ORDER BY id DESC
                LIMIT %s
                """,
                (
                    rows,
                    cols,
                    starting_color,
                    int(min_confiance),
                    prefix_norm,
                    prefix_norm + ",%",
                    prefix_mirror,
                    prefix_mirror + ",%",
                    limit,
                ),
            )
        else:
            cur.execute(
                """
                SELECT id, rows, cols, starting_color, status, winner, draw,
                       original_sequence, canonical_key, source_filename, created_at,
                       confiance
                FROM games
                WHERE rows=%s
                  AND cols=%s
                  AND starting_color=%s
                  AND status='FINISHED'
                  AND confiance >= %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (rows, cols, starting_color, int(min_confiance), limit),
            )

        return list(cur.fetchall())


def get_opening_stats(
    prefix_seq: str,
    rows: int,
    cols: int,
    starting_color: str,
    limit: int = 5000,
    min_confiance: int = 1,
) -> Dict[str, Any]:
    """
    Construit des stats sur les coups suivants après une position prefix_seq.

    Retour :
    {
      "prefix": ...,
      "total_games": ...,
      "moves": {
         4: {
            "games": 123,
            "wins_red": ...,
            "wins_yellow": ...,
            "draws": ...,
            "score_for_player_to_move": ...
         },
         ...
      }
    }
    Ici les clés de moves sont en 0-based (colonne 0..cols-1)
    """
    prefix_norm = normalize_sequence(prefix_seq, cols) if prefix_seq else ""
    prefix_len = len(_parse_seq(prefix_norm, cols)) if prefix_norm else 0

    candidates = get_position_candidates(
        prefix_seq=prefix_norm,
        rows=rows,
        cols=cols,
        starting_color=starting_color,
        limit=limit,
        min_confiance=min_confiance,
    )

    # déterminer à qui c'est le tour après prefix_seq
    turn = starting_color
    for _ in range(prefix_len):
        turn = YELLOW if turn == RED else RED

    stats: Dict[str, Any] = {
        "prefix": prefix_norm,
        "total_games": 0,
        "player_to_move": turn,
        "moves": {}
    }

    for g in candidates:
        seq = (g.get("original_sequence") or "").strip()
        if not seq:
            continue

        try:
            digits = _parse_seq(seq, cols)
        except Exception:
            continue

        if len(digits) <= prefix_len:
            continue

        next_col_0 = digits[prefix_len] - 1
        winner = g.get("winner")
        draw = bool(g.get("draw"))

        if next_col_0 not in stats["moves"]:
            stats["moves"][next_col_0] = {
                "games": 0,
                "wins_red": 0,
                "wins_yellow": 0,
                "draws": 0,
                "score_for_player_to_move": 0,
            }

        entry = stats["moves"][next_col_0]
        entry["games"] += 1
        stats["total_games"] += 1

        if draw:
            entry["draws"] += 1
        elif winner == RED:
            entry["wins_red"] += 1
        elif winner == YELLOW:
            entry["wins_yellow"] += 1

        # score vu du joueur qui doit jouer maintenant
        if draw:
            entry["score_for_player_to_move"] += 0
        elif winner == turn:
            entry["score_for_player_to_move"] += 2
        else:
            entry["score_for_player_to_move"] -= 1

    return stats


def get_best_book_move(
    prefix_seq: str,
    rows: int,
    cols: int,
    starting_color: str,
    limit: int = 5000,
    min_confiance: int = 1,
    min_games: int = 8,
) -> Optional[int]:
    """
    Retourne la meilleure colonne (0-based) depuis la BD pour une position donnée,
    ou None si pas assez de données.
    """
    stats = get_opening_stats(
        prefix_seq=prefix_seq,
        rows=rows,
        cols=cols,
        starting_color=starting_color,
        limit=limit,
        min_confiance=min_confiance,
    )

    best_col = None
    best_tuple = None

    for col, data in stats["moves"].items():
        games = int(data["games"])
        if games < min_games:
            continue

        score = int(data["score_for_player_to_move"])
        draws = int(data["draws"])

        # on préfère :
        # 1) score plus élevé
        # 2) plus d'échantillons
        # 3) plus de nulles qu'un coup très perdant
        candidate = (score, games, draws)

        if best_tuple is None or candidate > best_tuple:
            best_tuple = candidate
            best_col = int(col)

    return best_col


# ============================================================
# Import FINISHED (.txt)
# ============================================================

def insert_game_from_sequence(
    seq: str,
    rows: int,
    cols: int,
    starting_color: str,
    source_filename: Optional[str] = None,
    confiance: int = 1,
) -> Tuple[bool, str, Optional[int]]:
    seq = (seq or "").strip()
    if not seq:
        return (False, "Séquence vide: non enregistrée.", None)

    seq_norm = normalize_sequence(seq, cols)
    can = canonical_key(seq_norm, cols)

    try:
        moves = _simulate_moves_from_sequence(seq_norm, rows, cols, starting_color)
    except Exception as e:
        return (False, f"Séquence invalide: {e}", None)

    try:
        confiance = int(confiance)
    except Exception:
        confiance = 1

    if confiance < 0:
        confiance = 0
    if confiance > 10:
        confiance = 10

    with get_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                """
                INSERT INTO games(
                    rows, cols, starting_color, status, winner, draw,
                    original_sequence, canonical_key, source_filename,
                    confiance
                )
                VALUES (%s,%s,%s,'FINISHED',NULL,FALSE,%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    rows,
                    cols,
                    starting_color,
                    seq_norm,
                    can,
                    source_filename,
                    confiance,
                ),
            )
            gid = int(cur.fetchone()[0])

            for mv in moves:
                cur.execute(
                    """
                    INSERT INTO moves(game_id, ply, col, row, color)
                    VALUES (%s,%s,%s,%s,%s)
                    """,
                    (gid, mv["ply"], mv["col"], mv["row"], mv["color"]),
                )

            conn.commit()
            return (True, "Insérée + moves générés.", gid)

        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            return (False, "Déjà existante (identique/symétrique).", None)
        except Exception as e:
            conn.rollback()
            return (False, f"Erreur insert_game_from_sequence: {e}", None)


# ============================================================
# Auto-save App (IN_PROGRESS + FINISHED)
# ============================================================

def delete_game_by_source_filename(cur, source_filename: str) -> None:
    cur.execute(
        "DELETE FROM moves WHERE game_id IN (SELECT id FROM games WHERE source_filename=%s)",
        (source_filename,),
    )
    cur.execute("DELETE FROM games WHERE source_filename=%s", (source_filename,))


def upsert_game_progress(
    source_filename: str,
    seq: str,
    rows: int,
    cols: int,
    starting_color: str,
    status: str,
    winner: Optional[str],
    draw: bool,
    moves: List[Dict[str, Any]],
    confiance: int = 1,
) -> Tuple[bool, str, Optional[int]]:
    if not source_filename:
        return (False, "source_filename vide => refus", None)

    if not moves:
        return (False, "Aucun coup => non sauvegardé", None)

    if status not in ("IN_PROGRESS", "FINISHED"):
        status = "IN_PROGRESS"

    seq_norm = normalize_sequence(seq, cols) if seq else None
    can = canonical_key(seq_norm, cols) if seq_norm else None
    mir_norm = mirror_sequence(seq_norm, cols) if seq_norm else None

    try:
        confiance = int(confiance)
    except Exception:
        confiance = 1

    if confiance < 0:
        confiance = 0
    if confiance > 10:
        confiance = 10

    if status != "FINISHED":
        winner = None
        draw = False
    else:
        if draw:
            winner = None

    with get_conn() as conn, conn.cursor() as cur:
        try:
            # 1) Si EN COURS est préfixe d'une partie existante (ou miroir) => ne pas stocker
            if status == "IN_PROGRESS" and seq_norm:
                cur.execute(
                    """
                    SELECT id
                    FROM games
                    WHERE rows=%s AND cols=%s AND starting_color=%s
                      AND source_filename <> %s
                      AND original_sequence IS NOT NULL
                      AND (
                           original_sequence = %s
                        OR original_sequence LIKE %s
                        OR original_sequence = %s
                        OR original_sequence LIKE %s
                      )
                    LIMIT 1
                    """,
                    (
                        rows,
                        cols,
                        starting_color,
                        source_filename,
                        seq_norm,
                        seq_norm + ",%",
                        mir_norm,
                        mir_norm + ",%",
                    ),
                )
                pref = cur.fetchone()
                if pref:
                    delete_game_by_source_filename(cur, source_filename)
                    conn.commit()
                    return (
                        False,
                        "Déjà existante (début identique/symétrique) → non stockée.",
                        None,
                    )

            # 2) Si doublon exact / symétrique
            if can:
                cur.execute(
                    """
                    SELECT id
                    FROM games
                    WHERE rows=%s AND cols=%s AND starting_color=%s
                      AND canonical_key=%s
                      AND source_filename <> %s
                    LIMIT 1
                    """,
                    (rows, cols, starting_color, can, source_filename),
                )
                dup = cur.fetchone()
                if dup:
                    delete_game_by_source_filename(cur, source_filename)
                    conn.commit()
                    return (
                        False,
                        "Doublon identique/symétrique → partie courante supprimée.",
                        None,
                    )

            # 3) Upsert normal
            cur.execute(
                """
                INSERT INTO games(
                    rows, cols, starting_color, status, winner, draw,
                    original_sequence, canonical_key, source_filename,
                    confiance
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (source_filename)
                DO UPDATE SET
                    rows=EXCLUDED.rows,
                    cols=EXCLUDED.cols,
                    starting_color=EXCLUDED.starting_color,
                    status=EXCLUDED.status,
                    winner=EXCLUDED.winner,
                    draw=EXCLUDED.draw,
                    original_sequence=EXCLUDED.original_sequence,
                    canonical_key=EXCLUDED.canonical_key,
                    confiance=EXCLUDED.confiance
                RETURNING id
                """,
                (
                    rows,
                    cols,
                    starting_color,
                    status,
                    winner,
                    bool(draw),
                    seq_norm,
                    can,
                    source_filename,
                    confiance,
                ),
            )
            gid = int(cur.fetchone()[0])

            max_ply = max(int(m["ply"]) for m in moves)
            cur.execute("DELETE FROM moves WHERE game_id=%s AND ply > %s", (gid, max_ply))

            for mv in moves:
                cur.execute(
                    """
                    INSERT INTO moves(game_id, ply, col, row, color)
                    VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT (game_id, ply)
                    DO UPDATE SET col=EXCLUDED.col, row=EXCLUDED.row, color=EXCLUDED.color
                    """,
                    (
                        gid,
                        int(mv["ply"]),
                        int(mv["col"]),
                        int(mv["row"]),
                        str(mv["color"]),
                    ),
                )

            conn.commit()
            return (True, "Sauvegardé.", gid)

        except Exception as e:
            conn.rollback()
            return (False, f"Erreur upsert_game_progress: {e}", None)
