import os
import re
from typing import List, Optional, Tuple, Dict, Any

import psycopg2
import psycopg2.extras

RED = "R"
YELLOW = "Y"


# ---------------------- Connexion ----------------------
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


# ---------------------- Séquences (support cols>9) ----------------------
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


def _simulate_moves_from_sequence(
    seq: str, rows: int, cols: int, starting_color: str
) -> List[Dict[str, Any]]:
    """
    Transforme une séquence (ex: "3,1,3,1") en liste de moves avec (ply,col,row,color)
    col en base 0, row en base 0
    """
    seq_norm = normalize_sequence(seq, cols)
    digits = _parse_seq(seq_norm, cols)  # liste de colonnes 1..cols

    board = [[None for _ in range(cols)] for _ in range(rows)]
    moves: List[Dict[str, Any]] = []

    turn = starting_color
    for ply, d in enumerate(digits, start=1):
        col = d - 1

        # trouver la première case vide en partant du bas
        row = rows - 1
        while row >= 0 and board[row][col] is not None:
            row -= 1
        if row < 0:
            raise ValueError(f"Colonne pleine au coup {ply} (col={d})")

        board[row][col] = turn
        moves.append({"ply": ply, "col": col, "row": row, "color": turn})

        turn = YELLOW if turn == RED else RED

    return moves


# ---------------------- Tool Viewer: import .txt ----------------------
def parse_sequence_from_filename(path: str) -> str:
    name = os.path.basename(path)
    m = re.match(r"^([0-9]+)\.txt$", name)
    if not m:
        raise ValueError("Nom invalide. Exemple: 3131313.txt")
    return m.group(1)


# ---------------------- LIST / GET ----------------------
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


# ---------------------- Import FINISHED (.txt) ----------------------
def insert_game_from_sequence(
    seq: str,
    rows: int,
    cols: int,
    starting_color: str,
    source_filename: Optional[str] = None,
    confiance: int = 1,   # ✅ 0: exprès de perdre, 1: aléatoire, ...
) -> Tuple[bool, str, Optional[int]]:

    seq = (seq or "").strip()
    if not seq:
        return (False, "Séquence vide: non enregistrée.", None)

    seq_norm = normalize_sequence(seq, cols)
    can = canonical_key(seq_norm, cols)

    # On prépare les moves
    try:
        moves = _simulate_moves_from_sequence(seq_norm, rows, cols, starting_color)
    except Exception as e:
        return (False, f"Séquence invalide: {e}", None)

    # sécurité confiance
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

            # insérer les coups dans moves
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



# ---------------------- Auto-save App (IN_PROGRESS + FINISHED) ----------------------
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
    confiance: int = 1,  # ✅ 0: exprès de perdre, 1: aléatoire, ...
) -> Tuple[bool, str, Optional[int]]:

    if not source_filename:
        return (False, "source_filename vide => refus", None)

    if not moves:
        return (False, "Aucun coup => non sauvegardé", None)

    if status not in ("IN_PROGRESS", "FINISHED"):
        status = "IN_PROGRESS"

    # normaliser seq (format CSV) + canonical
    seq_norm = normalize_sequence(seq, cols) if seq else None
    can = canonical_key(seq_norm, cols) if seq_norm else None
    mir_norm = mirror_sequence(seq_norm, cols) if seq_norm else None

    # clamp confiance (sécurité)
    try:
        confiance = int(confiance)
    except Exception:
        confiance = 1
    if confiance < 0:
        confiance = 0
    if confiance > 10:
        confiance = 10

    # Si pas FINISHED : on neutralise résultat
    if status != "FINISHED":
        winner = None
        draw = False
    else:
        if draw:
            winner = None

    with get_conn() as conn, conn.cursor() as cur:
        try:
            # ------------------------------------------------------------
            # 1) Si EN COURS est un DÉBUT (prefix) d'une partie existante
            #    (ou de son miroir), alors on ne stocke pas.
            # ------------------------------------------------------------
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

            # ------------------------------------------------------------
            # 2) Si identique/symétrique exact (canonical), on supprime la courante
            # ------------------------------------------------------------
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

            # ------------------------------------------------------------
            # 3) Sauvegarde normale (upsert par source_filename)
            #    ✅ on enregistre confiance (prof)
            # ------------------------------------------------------------
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

            # Nettoyage: si l'utilisateur a "reculé", on supprime les moves au-delà
            max_ply = max(int(m["ply"]) for m in moves)
            cur.execute("DELETE FROM moves WHERE game_id=%s AND ply > %s", (gid, max_ply))

            # Upsert des moves
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


def get_game_with_moves(game_id: int):
    """
    Pour Tool Viewer: retourne (game_dict, moves_list)
    Nécessite tables: games, moves
    """
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
