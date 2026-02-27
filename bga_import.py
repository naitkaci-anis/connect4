from typing import List, Dict, Any, Optional

def _moves_to_sequence_csv(moves: List[Dict[str, Any]], cols: int) -> str:
    cols_raw = []
    for m in moves or []:
        c = (m or {}).get("col", None)
        if c is None:
            continue
        try:
            cols_raw.append(int(c))
        except Exception:
            continue

    if not cols_raw:
        return ""

    is_zero_based = (min(cols_raw) == 0)

    out = []
    for c in cols_raw:
        if is_zero_based:
            if 0 <= c <= cols - 1:
                out.append(c + 1)
        else:
            if 1 <= c <= cols:
                out.append(c)

    return ",".join(str(x) for x in out)

def import_bga_moves(
    moves: List[Dict[str, Any]],
    rows: int,
    cols: int,
    confiance: int = 3,
    source_filename: Optional[str] = None,
    starting_color: str = "R",
) -> int:
    import db

    seq = _moves_to_sequence_csv(moves, cols).strip()
    if not seq:
        raise ValueError("Séquence vide / aucun coup exploitable")

    ok, msg, gid = db.insert_game_from_sequence(
        seq=seq,
        rows=rows,
        cols=cols,
        starting_color=starting_color,
        source_filename=source_filename,
        confiance=confiance,
    )
    if not ok or gid is None:
        raise RuntimeError(msg)

    return gid
