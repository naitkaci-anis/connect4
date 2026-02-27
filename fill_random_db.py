import time
import random
from typing import List, Dict, Any, Optional, Tuple

import db  # ton db.py

RED = "R"
YELLOW = "Y"
EMPTY = None


def check_winner(board: List[List[Optional[str]]], r: int, c: int, color: str) -> bool:
    rows = len(board)
    cols = len(board[0])

    def count_dir(dr: int, dc: int) -> int:
        cnt = 0
        rr, cc = r + dr, c + dc
        while 0 <= rr < rows and 0 <= cc < cols and board[rr][cc] == color:
            cnt += 1
            rr += dr
            cc += dc
        return cnt

    # 4 directions: horiz, vert, diag1, diag2
    dirs = [(0, 1), (1, 0), (1, 1), (1, -1)]
    for dr, dc in dirs:
        total = 1 + count_dir(dr, dc) + count_dir(-dr, -dc)
        if total >= 4:
            return True
    return False


def play_random_game(rows: int, cols: int, starting_color: str, rng: random.Random) -> Tuple[str, List[Dict[str, Any]], Optional[str], bool]:
    board: List[List[Optional[str]]] = [[EMPTY for _ in range(cols)] for _ in range(rows)]
    heights = [rows - 1] * cols  # prochaine ligne libre (en partant du bas)
    seq_cols_1based: List[int] = []
    moves_payload: List[Dict[str, Any]] = []

    turn = starting_color
    ply = 0

    while True:
        valid = [c for c in range(cols) if heights[c] >= 0]
        if not valid:
            # draw
            seq = ",".join(str(x) for x in seq_cols_1based)
            return seq, moves_payload, None, True

        c = rng.choice(valid)
        r = heights[c]
        heights[c] -= 1

        board[r][c] = turn
        ply += 1
        seq_cols_1based.append(c + 1)

        moves_payload.append({"ply": ply, "col": c, "row": r, "color": turn})

        if check_winner(board, r, c, turn):
            seq = ",".join(str(x) for x in seq_cols_1based)
            return seq, moves_payload, turn, False

        turn = YELLOW if turn == RED else RED


def main():
    # ---- paramètres mission ----
    ROWS = 9
    COLS = 9
    START = RED

    N = 300  # nombre de parties à générer
    SEED = 42  # change si tu veux

    rng = random.Random(SEED)

    inserted = 0
    skipped = 0

    for i in range(1, N + 1):
        seq, moves, winner, draw = play_random_game(ROWS, COLS, START, rng)

        source_filename = f"random_{ROWS}x{COLS}_{int(time.time()*1000)}_{i}"

        ok, msg, gid = db.upsert_game_progress(
            source_filename=source_filename,
            seq=seq,
            rows=ROWS,
            cols=COLS,
            starting_color=START,
            status="FINISHED",
            winner=winner,
            draw=draw,
            moves=moves,
            confiance=1,  # 1 = aléatoire
        )

        if ok:
            inserted += 1
            print(f"[OK] #{i} -> game_id={gid} winner={winner} draw={draw} ({msg})")
        else:
            skipped += 1
            print(f"[SKIP] #{i} -> {msg}")

    print("\n==== FIN ====")
    print("Insérées:", inserted)
    print("Ignorées:", skipped)


if __name__ == "__main__":
    main()
