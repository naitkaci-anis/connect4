# controller.py
# Contrôleur (colle la vue et le core, gère la logique d’actions)

import json
import os
import time
from dataclasses import asdict
from typing import Optional, List, Dict, Any

from core import (
    ensure_config,
    Connect4,
    Move,
    GameSnapshot,
    RED,
    YELLOW,
    EMPTY,
    COLOR_NAME,
    SAVES_DIR,
    minimax_score_for_column,
    pick_best,
)

# ---- DB (Mission 2) : optionnel ----
DB_AVAILABLE = False
try:
    import db
    DB_AVAILABLE = True
except Exception as e:
    import traceback
    print("DB IMPORT ERROR:", e)
    traceback.print_exc()
    DB_AVAILABLE = False




class Controller:
    def __init__(self, view):
        self.view = view

        self.cfg = ensure_config()
        self.game = Connect4(
            self.cfg["rows"], self.cfg["cols"], self.cfg["starting_color"]
        )
        self.game.mode = 2

        self.cell = self.cfg["cell_size"]
        self.margin = self.cfg["margin"]
        self.delay = self.cfg["drop_delay_ms"]

        self._auto_job = None
        self._think_job = None
        self._ai_scores: List[Optional[int]] = [None] * self.game.cols
        self._think_index = 0
        self._thinking = False

        self.match_score = {RED: 0, YELLOW: 0}
        self._counted_games: Dict[int, str] = {}

        # DB: si on charge depuis DB, on garde source_filename pour sauvegarder sur la même "ligne"
        self._db_source_override: Optional[str] = None

    # ---------- lifecycle ----------
    def start(self):
        # init view dims
        self.view.resize_canvas(
            self.game.rows, self.game.cols, self.cell, self.margin, self.delay
        )

        # auto-load db
        self._autoload_in_progress_from_db_if_possible()

        # render + autoplay
        self._render_all()
        self._maybe_autoplay()

    def on_close(self):
        self._cancel_autoplay()
        self._cancel_thinking()
        self._save_game_to_db_if_possible()
        self.view.destroy()

    # ---------- helpers ----------
    def _human_can_play_now(self) -> bool:
        if self.game.mode == 2:
            return True
        if self.game.mode == 1:
            return self.game.current_turn == RED
        return False

    def _col_from_xy(self, x: int, y: int) -> Optional[int]:
        m, s = self.margin, self.cell
        y0 = self.view.top_pad

        if y < (y0 + m) or y > (y0 + m + self.game.rows * s):
            return None
        if x < m or x > m + self.game.cols * s:
            return None

        col = int((x - m) // s)
        if 0 <= col < self.game.cols:
            return col
        return None

    # ---------- rendering ----------
    def _update_match_score_if_needed(self):
        g = self.game
        
        if g.cursor <= 0: return

        
        if not g.finished:
            if g.game_index in self._counted_games:
                prev = self._counted_games.pop(g.game_index)
                if prev in (RED, YELLOW):
                    self.match_score[prev] = max(0, self.match_score[prev] - 1)
            return

        if g.game_index in self._counted_games:
            return

        if g.draw:
            self._counted_games[g.game_index] = "D"
        else:
            self._counted_games[g.game_index] = g.winner or ""
            if g.winner in (RED, YELLOW):
                self.match_score[g.winner] += 1

    def _build_status_text(self) -> str:
        g = self.game
        mode_txt = ["0J", "1J", "2J"][g.mode]
        score_txt = f"Score: {COLOR_NAME[RED]} {self.match_score[RED]} - {self.match_score[YELLOW]} {COLOR_NAME[YELLOW]}"

        algo = self.view.get_algo()
        depth = max(1, min(self.view.get_depth(), 8))

        if g.finished:
            if g.draw:
                txt = f"[Partie #{g.game_index} | {mode_txt}] Fin : ÉGALITÉ."
            else:
                txt = f"[Partie #{g.game_index} | {mode_txt}] Fin : {COLOR_NAME[g.winner]} gagne !"
        else:
            turn = COLOR_NAME[g.current_turn]
            paused = " (PAUSE)" if g.paused else ""
            txt = f"[Partie #{g.game_index} | {mode_txt}] À jouer : {turn}{paused}   | Robot: {algo}"
            if algo == "MiniMax":
                txt += f" (d={depth})"

        txt += f"   | coups: {g.cursor}/{len(g.moves)}"
        txt += "   | " + score_txt
        return txt

    def _render_all(self):
        self._update_match_score_if_needed()
        self._save_game_to_db_if_possible()  # autosave

        self.view.render(
            board=self.game.board,
            winning_line=self.game.winning_line,
            ai_scores=self._ai_scores,
            thinking=self._thinking,
            status_text=self._build_status_text(),
            cursor=self.game.cursor,
            total=len(self.game.moves),
            paused=self.game.paused,
        )

    # ---------- events from view ----------
    def on_mode_change(self):
        self._cancel_autoplay()
        self._cancel_thinking()

        self.game.mode = self.view.get_mode()
        self._ai_scores = [None] * self.game.cols
        self._render_all()
        self._maybe_autoplay()

    def on_robot_change(self):
        self._cancel_autoplay()
        self._cancel_thinking()

        self._ai_scores = [None] * self.game.cols
        self._render_all()
        self._maybe_autoplay()

    def on_new_game(self):
        self._cancel_autoplay()
        self._cancel_thinking()

        mode = self.view.get_mode()
        self._db_source_override = None  # nouvelle partie => ui_game_{index}

        self.game = Connect4(
            self.cfg["rows"], self.cfg["cols"], self.cfg["starting_color"]
        )
        self.game.mode = mode

        self._ai_scores = [None] * self.game.cols
        self.view.resize_canvas(
            self.game.rows, self.game.cols, self.cell, self.margin, self.delay
        )
        self._render_all()
        self._maybe_autoplay()

    def on_toggle_pause(self):
        self._cancel_autoplay()
        self._cancel_thinking()

        self.game.paused = not self.game.paused
        self._render_all()
        self._maybe_autoplay()

    def on_undo(self):
        self._cancel_autoplay()
        self._cancel_thinking()

        self.game.undo()
        self._ai_scores = [None] * self.game.cols
        self._render_all()
        self._maybe_autoplay()

    def on_redo(self):
        self._cancel_autoplay()
        self._cancel_thinking()

        self.game.redo()
        self._ai_scores = [None] * self.game.cols
        self._render_all()
        self._maybe_autoplay()

    def on_canvas_click(self, x: int, y: int):
        if not self.game.can_play():
            return
        if not self._human_can_play_now():
            return

        col = self._col_from_xy(x, y)
        if col is None:
            return

        played = self.game.drop_in_column(col)
        if not played:
            self.view.bell()
            return

        self._ai_scores = [None] * self.game.cols
        self._render_all()
        self._maybe_autoplay()

    def on_slider(self, value):
        try:
            val = int(float(value))
        except Exception:
            return
        if val == self.game.cursor:
            return

        self._cancel_autoplay()
        self._cancel_thinking()

        self.game.apply_to_cursor(val)
        self._ai_scores = [None] * self.game.cols
        self._render_all()
        self._maybe_autoplay()

    # ---------- autoplay / bots ----------
    def _maybe_autoplay(self):
        self._cancel_autoplay()
        self._cancel_thinking()

        g = self.game
        if not g.can_play() or g.finished:
            return

        if g.mode == 2:
            return
        if g.mode == 1 and g.current_turn == YELLOW:
            self._schedule_robot_move()
            return
        if g.mode == 0:
            self._schedule_robot_move()
            return

    def _schedule_robot_move(self):
        algo = self.view.get_algo()
        if algo == "MiniMax":
            self._start_thinking_minimax()
        else:
            self._auto_job = self.view.after(self.delay, self._random_move)

    def _cancel_autoplay(self):
        if self._auto_job is not None:
            try:
                self.view.after_cancel(self._auto_job)
            except Exception:
                pass
            self._auto_job = None

    def _random_move(self):
        self._auto_job = None
        g = self.game
        if not g.can_play() or g.finished:
            return
        valid = g.valid_columns()
        if not valid:
            return
        idx = int(time.time() * 1000) % len(valid)
        g.drop_in_column(valid[idx])
        self._ai_scores = [None] * g.cols
        self._render_all()
        self._maybe_autoplay()

    def _cancel_thinking(self):
        self._thinking = False
        if self._think_job is not None:
            try:
                self.view.after_cancel(self._think_job)
            except Exception:
                pass
            self._think_job = None

    def _start_thinking_minimax(self):
        g = self.game
        if not g.can_play() or g.finished:
            return

        depth = max(1, min(self.view.get_depth(), 8))

        self._thinking = True
        self._ai_scores = [None] * g.cols
        self._think_index = 0
        self._render_all()

        def step():
            if not g.can_play() or g.finished:
                self._cancel_thinking()
                return

            cols = g.cols
            if self._think_index >= cols:
                self._thinking = False
                best = pick_best(self._ai_scores)
                g.drop_in_column(best)
                self._ai_scores = [None] * g.cols
                self._render_all()
                self._maybe_autoplay()
                return

            c = self._think_index
            self._think_index += 1

            if g.board[0][c] != EMPTY:
                self._ai_scores[c] = None
            else:
                tmp = [row[:] for row in g.board]
                self._ai_scores[c] = minimax_score_for_column(
                    tmp, c, depth, g.current_turn
                )

            self._render_all()
            self._think_job = self.view.after(50, step)

        self._think_job = self.view.after(50, step)

    # ---------- JSON save/load ----------
    def on_save_json(self):
        os.makedirs(SAVES_DIR, exist_ok=True)
        snap = self.game.to_snapshot()
        data = asdict(snap)

        default_name = f"partie_{snap.game_index:04d}.json"
        path = self.view.ask_save_path(initialdir=SAVES_DIR, initialfile=default_name)
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.view.info("Sauvegarde", f"Partie sauvegardée:\n{path}")
        except Exception as e:
            self.view.error("Erreur", f"Impossible de sauvegarder:\n{e}")

    def on_load_json(self):
        os.makedirs(SAVES_DIR, exist_ok=True)
        path = self.view.ask_load_path(initialdir=SAVES_DIR)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            snap = GameSnapshot(**data)

            self._cancel_autoplay()
            self._cancel_thinking()

            self.game = Connect4.from_snapshot(snap)
            self.view.set_mode(self.game.mode)
            self._ai_scores = [None] * self.game.cols

            # charger JSON => ne pas continuer la même ligne DB
            self._db_source_override = None

            self.view.resize_canvas(
                self.game.rows, self.game.cols, self.cell, self.margin, self.delay
            )
            self._render_all()
            self._maybe_autoplay()
        except Exception as e:
            self.view.error("Erreur", f"Impossible de charger:\n{e}")

    # ---------- Settings ----------
    def on_open_settings(self):
        self.view.open_settings_dialog(self.cfg, self._apply_new_config)

    def _apply_new_config(self, new_cfg: Dict[str, Any]):
        # mettre à jour cfg locale
        self.cfg = new_cfg
        self.cell = int(new_cfg["cell_size"])
        self.margin = int(new_cfg["margin"])
        self.delay = int(new_cfg["drop_delay_ms"])

        self._cancel_autoplay()
        self._cancel_thinking()

        # changement config => nouvelle partie => DB override reset
        self._db_source_override = None

        self.game = Connect4(
            int(new_cfg["rows"]), int(new_cfg["cols"]), str(new_cfg["starting_color"])
        )
        self.game.mode = self.view.get_mode()

        self._ai_scores = [None] * self.game.cols
        self.view.resize_canvas(
            self.game.rows, self.game.cols, self.cell, self.margin, self.delay
        )
        self._render_all()
        self._maybe_autoplay()

    # ---------- DB ----------
    def _save_game_to_db_if_possible(self):
        """
        Sauvegarde AUTOMATIQUE dans PostgreSQL même si IN_PROGRESS.
        Nécessite db.upsert_game_progress et uq_games_source_filename.
        """
        if not DB_AVAILABLE:
            return

        g = self.game
        source = self._db_source_override or f"ui_game_{g.game_index}"

        seq = ",".join(str(m.col + 1) for m in g.moves[: g.cursor])


        status = "FINISHED" if g.finished else "IN_PROGRESS"
        winner = g.winner if (g.finished and not g.draw) else None
        draw = bool(g.draw) if g.finished else False

        moves_payload = []
        for i, m in enumerate(g.moves[: g.cursor], start=1):
            moves_payload.append(
                {"ply": i, "col": int(m.col), "row": int(m.row), "color": m.color}
            )

        try:
            ok, msg, gid = db.upsert_game_progress(
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
            print("DB SAVE:", ok, msg, gid, "source_filename=", source)
        except Exception as e:
            import traceback
            print("DB SAVE ERROR:", e)
            traceback.print_exc()


    def _autoload_in_progress_from_db_if_possible(self):
        if not DB_AVAILABLE:
            return
        try:
            g = db.get_latest_in_progress()
        except Exception:
            return
        if not g:
            return
        src = str(g.get("source_filename") or "")
        if not src.startswith("ui_game_"):
            return
        self.load_from_db(int(g["id"]), silent=True)

    def on_load_db_popup(self):
        if not DB_AVAILABLE:
            self.view.error("DB", "DB non disponible (psycopg2/DATABASE_URL).")
            return

        try:
            inprog = db.list_in_progress(limit=5000)
            allg = db.list_games(limit=5000)
            seen = set()
            rows = []
            for gg in inprog + allg:
                if gg["id"] in seen:
                    continue
                seen.add(gg["id"])
                rows.append(gg)
        except Exception as e:
            self.view.error("DB", str(e))
            return

        gid = self.view.ask_db_choice(rows)
        if gid is None:
            return
        self.load_from_db(int(gid), silent=False)

    def load_from_db(self, game_id: int, silent: bool = False):
        if not DB_AVAILABLE:
            return
        try:
            data = db.get_game_for_app(game_id)
        except Exception as e:
            if not silent:
                self.view.error("DB", str(e))
            return

        current_mode = self.view.get_mode()

        self._cancel_autoplay()
        self._cancel_thinking()

        rows = int(data["rows"])
        cols = int(data["cols"])
        start = data["starting_color"]

        self.game = Connect4(rows, cols, start)
        self.game.mode = current_mode

        src = data.get("source_filename")
        self._db_source_override = src if src else f"db_game_{data['id']}"

        self.game.moves = []
        for mv in data["moves"]:
            self.game.moves.append(
                Move(
                    col=int(mv["col"]),
                    row=int(mv["row"]),
                    color=mv["color"],
                    timestamp=time.time(),
                )
            )

        self.game.apply_to_cursor(len(self.game.moves))

        self._ai_scores = [None] * self.game.cols
        self.view.resize_canvas(
            self.game.rows, self.game.cols, self.cell, self.margin, self.delay
        )
        self._render_all()
        self._maybe_autoplay()

        if not silent:
            self.view.info("DB", f"Partie chargée depuis DB: #{data['id']}")
