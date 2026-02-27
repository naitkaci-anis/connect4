import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import db  # IMPORTANT: doit être le db.py de TON dossier

EMPTY = "."
COLOR_FILL = {"R": "#e53935", "Y": "#fdd835", ".": "#ffffff"}

# --- Palette UI ---
UI_BG = "#1f2937"  # fond général (gris-bleu)
CARD_BG = "#2b3443"  # cartes/panneaux
CARD_INNER = "#111827"  # zone tableau/canvas (reste sombre mais lisible)

TEXT_FG = "#f3f4f6"  # texte principal (plus clair)
MUTED_FG = "#cbd5e1"
BTN_BG = "#2563eb"
BTN_HOVER = "#1d4ed8"
BORDER = "#1f2937"

BOARD_BG = "#1565c0"
OUTLINE = "#263238"


class Viewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Mission 2.2 — ToolViewer DB (Puissance 4)")
        self.configure(bg=UI_BG)
        self.minsize(1200, 700)

        # --- DEBUG import db ---
        try:
            print("=== DB DEBUG ===")
            print("CWD:", os.getcwd())
            print("DB LOADED FROM:", getattr(db, "__file__", "<no file>"))
            print("HAS get_game_with_moves:", hasattr(db, "get_game_with_moves"))
            print("================")
        except Exception:
            pass

        if not hasattr(db, "get_game_with_moves"):
            msg = (
                "Ton module db importé ne contient PAS la fonction get_game_with_moves.\n\n"
                f"db importé depuis : {getattr(db, '__file__', '<inconnu>')}\n\n"
                "✅ Solution:\n"
                "1) tool_viewer.py et db.py dans le MÊME dossier.\n"
                "2) Lance: python tool_viewer.py depuis ce dossier.\n"
                "3) Supprime __pycache__.\n"
            )
            messagebox.showerror("DB", msg)

        # --- état (inchangé) ---
        self.rows = 8
        self.cols = 9
        self.cell = 52
        self.margin = 14

        self.games = []
        self.sym_games = []

        self.game_id = None
        self.game = None
        self.moves = []
        self.cursor = 0

        self.show_mirror = tk.BooleanVar(value=False)

        self._setup_style()
        self._build_ui()
        self.refresh_list()

    # =========================
    # ========== UI ===========
    # =========================
    def _setup_style(self):
        style = ttk.Style(self)
        for th in ("clam", "alt", "default"):
            try:
                style.theme_use(th)
                break
            except Exception:
                pass

        style.configure(".", font=("Segoe UI", 10))
        style.configure("App.TFrame", background=UI_BG)
        style.configure("Card.TFrame", background=CARD_BG)
        style.configure("Inner.TFrame", background=CARD_INNER)

        style.configure(
            "Title.TLabel",
            background=CARD_BG,
            foreground=TEXT_FG,
            font=("Segoe UI", 11, "bold"),
        )
        style.configure("Hint.TLabel", background=CARD_BG, foreground=MUTED_FG)
        style.configure("Info.TLabel", background=CARD_BG, foreground=TEXT_FG)

        style.configure(
            "Accent.TButton",
            padding=(12, 8),
            background=BTN_BG,
            foreground="white",
            relief="flat",
        )
        style.map("Accent.TButton", background=[("active", BTN_HOVER)])

        style.configure(
            "Ghost.TButton",
            padding=(10, 8),
            background=CARD_BG,
            foreground=TEXT_FG,
            relief="flat",
        )
        style.map("Ghost.TButton", background=[("active", BORDER)])

        style.configure("Switch.TCheckbutton", background=CARD_BG, foreground=TEXT_FG)
        style.map("Switch.TCheckbutton", background=[("active", CARD_BG)])

        style.configure("App.Horizontal.TScale", background=CARD_BG, troughcolor=BORDER)

        # Treeview styling
        style.configure(
            "Table.Treeview",
            background=CARD_INNER,
            fieldbackground=CARD_INNER,
            foreground=TEXT_FG,
            rowheight=26,
            bordercolor=BORDER,
            borderwidth=1,
        )
        style.map(
            "Table.Treeview",
            background=[("selected", BTN_BG)],
            foreground=[("selected", "white")],
        )
        style.configure(
            "Table.Treeview.Heading",
            background=CARD_BG,
            foreground=TEXT_FG,
            relief="flat",
            font=("Segoe UI", 10, "bold"),
        )
        style.map("Table.Treeview.Heading", background=[("active", BORDER)])

    def _build_ui(self):
        root = ttk.Frame(self, style="App.TFrame", padding=12)
        root.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        paned = ttk.Panedwindow(root, orient="horizontal")
        paned.grid(row=0, column=0, sticky="nsew")
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)

        left_card = ttk.Frame(paned, style="Card.TFrame", padding=12)
        right_card = ttk.Frame(paned, style="Card.TFrame", padding=12)
        paned.add(left_card, weight=2)
        paned.add(right_card, weight=3)

        # LEFT
        left_card.columnconfigure(0, weight=1)
        left_card.rowconfigure(1, weight=1)
        left_card.rowconfigure(4, weight=1)

        ttk.Label(left_card, text="Parties (DB)", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )

        # table games
        games_wrap = ttk.Frame(left_card, style="Inner.TFrame", padding=8)
        games_wrap.grid(row=2, column=0, sticky="nsew")
        games_wrap.rowconfigure(0, weight=1)
        games_wrap.columnconfigure(0, weight=1)

        self.games_tree = ttk.Treeview(
            games_wrap,
            columns=("id", "status", "seq", "winner", "draw", "canon", "src", "confiance"),
            show="headings",
            style="Table.Treeview",
            selectmode="browse",
        )

        self.games_tree.grid(row=0, column=0, sticky="nsew")
        self.games_tree.bind("<<TreeviewSelect>>", self._on_pick)

        ysb = ttk.Scrollbar(
            games_wrap, orient="vertical", command=self.games_tree.yview
        )
        ysb.grid(row=0, column=1, sticky="ns")
        xsb = ttk.Scrollbar(
            games_wrap, orient="horizontal", command=self.games_tree.xview
        )
        xsb.grid(row=1, column=0, sticky="ew")
        self.games_tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)

        self._setup_games_tree_columns()

        # actions
        actions = ttk.Frame(left_card, style="Card.TFrame")
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 8))

        ttk.Button(
            actions, text="Rafraîchir", command=self.refresh_list, style="Ghost.TButton"
        ).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(
            actions,
            text="Importer .txt",
            command=self.import_txt,
            style="Accent.TButton",
        ).grid(row=0, column=1, padx=(0, 8))
        ttk.Checkbutton(
            actions,
            text="Afficher miroir",
            variable=self.show_mirror,
            command=self._on_toggle_mirror,
            style="Switch.TCheckbutton",
        ).grid(row=0, column=2, padx=(6, 0))

        ttk.Label(left_card, text="Série ", style="Title.TLabel").grid(
            row=4, column=0, sticky="w", pady=(14, 6)
        )

        # table symmetries
        sym_wrap = ttk.Frame(left_card, style="Inner.TFrame", padding=8)
        sym_wrap.grid(row=6, column=0, sticky="nsew")
        sym_wrap.rowconfigure(0, weight=1)
        sym_wrap.columnconfigure(0, weight=1)

        self.sym_tree = ttk.Treeview(
            sym_wrap,
            columns=("id", "status", "seq", "winner", "draw"),
            show="headings",
            style="Table.Treeview",
            selectmode="browse",
        )
        self.sym_tree.grid(row=0, column=0, sticky="nsew")
        self.sym_tree.bind("<<TreeviewSelect>>", self._on_pick_sym)

        ysb2 = ttk.Scrollbar(sym_wrap, orient="vertical", command=self.sym_tree.yview)
        ysb2.grid(row=0, column=1, sticky="ns")
        self.sym_tree.configure(yscrollcommand=ysb2.set)
        self._setup_sym_tree_columns()

        # RIGHT
        right_card.columnconfigure(0, weight=1)
        right_card.rowconfigure(2, weight=1)

        ttk.Label(right_card, text="Plateau", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.info = ttk.Label(
            right_card,
            text="Sélectionne une partie.",
            style="Info.TLabel",
            anchor="w",
            wraplength=760,
        )
        self.info.grid(row=1, column=0, sticky="ew", pady=(6, 10))

        canvas_wrap = ttk.Frame(right_card, style="Inner.TFrame", padding=10)
        canvas_wrap.grid(row=2, column=0, sticky="nsew")
        canvas_wrap.rowconfigure(0, weight=1)
        canvas_wrap.columnconfigure(0, weight=1)

        w = self.margin * 2 + self.cols * self.cell
        h = self.margin * 2 + self.rows * self.cell
        self.canvas = tk.Canvas(
            canvas_wrap,
            width=w,
            height=h,
            bg=CARD_INNER,
            highlightthickness=1,
            highlightbackground=BORDER,
            relief="flat",
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")

        nav = ttk.Frame(right_card, style="Card.TFrame")
        nav.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        nav.columnconfigure(3, weight=1)

        ttk.Button(nav, text="|<", command=self.first, style="Ghost.TButton").grid(
            row=0, column=0, padx=(0, 6)
        )
        ttk.Button(nav, text="<", command=self.prev_step, style="Ghost.TButton").grid(
            row=0, column=1, padx=(0, 6)
        )

        self.slider = ttk.Scale(
            nav,
            from_=0,
            to=0,
            orient="horizontal",
            command=self._on_slider,
            style="App.Horizontal.TScale",
        )
        self.slider.grid(row=0, column=3, sticky="ew", padx=10)

        ttk.Button(nav, text=">", command=self.next_step, style="Ghost.TButton").grid(
            row=0, column=4, padx=(6, 6)
        )
        ttk.Button(nav, text=">|", command=self.last, style="Ghost.TButton").grid(
            row=0, column=5, padx=(0, 10)
        )

        self.step_lbl = ttk.Label(nav, text="0/0", anchor="e", style="Info.TLabel")
        self.step_lbl.grid(row=0, column=6, sticky="e")

    def _setup_games_tree_columns(self):
        cols = [
            ("id", 70, "center", "ID"),
            ("status", 110, "center", "Status"),
            ("seq", 180, "w", "Seq"),
            ("winner", 70, "center", "Winner"),
            ("draw", 60, "center", "Draw"),
            ("canon", 180, "w", "Canonical"),
            ("src", 260, "w", "Source"),
            ("confiance", 90, "center", "Confiance"),
        ]
        for key, width, anchor, title in cols:
            self.games_tree.heading(key, text=title)
            self.games_tree.column(
                key,
                width=width,
                anchor=anchor,
                stretch=(key in ("seq", "canon", "src")),
            )

    def _setup_sym_tree_columns(self):
        cols = [
            ("id", 70, "center", "ID"),
            ("status", 110, "center", "Status"),
            ("seq", 220, "w", "Seq"),
            ("winner", 70, "center", "Winner"),
            ("draw", 60, "center", "Draw"),
        ]
        for key, width, anchor, title in cols:
            self.sym_tree.heading(key, text=title)
            self.sym_tree.column(
                key, width=width, anchor=anchor, stretch=(key == "seq")
            )

    # =========================
    # ====== LOGIQUE DB =======
    # =========================
    def _on_toggle_mirror(self):
        self._refresh_series_list()
        self._render()

    def refresh_list(self):
        try:
            self.games = db.list_games(limit=5000)
        except Exception as e:
            messagebox.showerror(
                "DB", f"{e}\n\n(db importé depuis: {getattr(db,'__file__','?')})"
            )
            return

        # clear tree
        for iid in self.games_tree.get_children():
            self.games_tree.delete(iid)

        for g in self.games:
            seq = str(g.get("original_sequence") or "")
            status = str(g.get("status") or "")
            winner = str(g.get("winner") or "")
            draw = "1" if g.get("draw") else ""
            canon = str(g.get("canonical_key") or "")
            src = str(g.get("source_filename") or "")
            conf = g.get("confiance")
            conf = "" if conf is None else str(conf)

            self.games_tree.insert(
                "",
                "end",
                iid=str(g["id"]),
                values=(g["id"], status, seq, winner, draw, canon, src, conf),
            )



        # reset right
        for iid in self.sym_tree.get_children():
            self.sym_tree.delete(iid)
        self.sym_games = []
        self.game_id = None
        self.game = None
        self.moves = []
        self.cursor = 0
        self.slider.configure(to=0)
        self.slider.set(0)
        self.step_lbl.config(text="0/0")
        self.info.config(text="Sélectionne une partie.")
        self.canvas.delete("all")

    def import_txt(self):
        path = filedialog.askopenfilename(filetypes=[("TXT", "*.txt")])
        if not path:
            return

        try:
            seq = db.parse_sequence_from_filename(path)
        except Exception as e:
            messagebox.showerror("Import", str(e))
            return

        rows, cols, start = 8, 9, "R"

        try:
            inserted, msg, gid = db.insert_game_from_sequence(
                seq, rows, cols, start, source_filename=path
            )
        except Exception as e:
            messagebox.showerror("DB", str(e))
            return

        messagebox.showinfo("Import", msg)
        self.refresh_list()

        if inserted and gid:
            sel = str(gid)
            if sel in self.games_tree.get_children():
                self.games_tree.selection_set(sel)
                self.games_tree.see(sel)
                self.games_tree.event_generate("<<TreeviewSelect>>")

    def _on_pick(self, _evt=None):
        sel = self.games_tree.selection()
        if not sel:
            return
        gid = int(sel[0])
        self.load_game(gid)

    def _on_pick_sym(self, _evt=None):
        sel = self.sym_tree.selection()
        if not sel:
            return
        gid = int(sel[0])
        self.load_game(gid)

    def load_game(self, game_id: int):
        if not hasattr(db, "get_game_with_moves"):
            messagebox.showerror(
                "DB",
                f"db.get_game_with_moves introuvable.\n(db: {getattr(db,'__file__','?')})",
            )
            return

        try:
            game, moves = db.get_game_with_moves(game_id)
        except Exception as e:
            messagebox.showerror("DB", str(e))
            return

        self.game_id = game_id
        self.game = game
        self.moves = moves

        self.rows = int(game["rows"])
        self.cols = int(game["cols"])

        self.cursor = len(moves)
        self.slider.configure(to=len(moves))
        self.slider.set(self.cursor)
        self.step_lbl.config(text=f"{self.cursor}/{len(moves)}")

        try:
            self.sym_games = (
                db.list_symmetries(game_id) if hasattr(db, "list_symmetries") else []
            )
        except Exception:
            self.sym_games = []

        self._refresh_series_list()
        self._render()

    def _refresh_series_list(self):
        for iid in self.sym_tree.get_children():
            self.sym_tree.delete(iid)

        if not self.sym_games:
            return

        mirror_on = bool(self.show_mirror.get())

        for sg in self.sym_games:
            sid = int(sg["id"])
            status = str(sg.get("status") or "")
            seq = str(sg.get("original_sequence") or "")

            if mirror_on and seq and hasattr(db, "mirror_sequence"):
                try:
                    seq = db.mirror_sequence(seq, self.cols)
                except Exception:
                    pass

            winner = str(sg.get("winner") or "")
            draw = "1" if sg.get("draw") else ""

            self.sym_tree.insert(
                "", "end", iid=str(sid), values=(sid, status, seq, winner, draw)
            )

    # navigation
    def _on_slider(self, _val):
        if not self.game:
            return
        try:
            self.cursor = int(float(self.slider.get()))
        except Exception:
            return
        self._render()

    def first(self):
        if not self.game:
            return
        self.cursor = 0
        self.slider.set(0)
        self._render()

    def last(self):
        if not self.game:
            return
        self.cursor = len(self.moves)
        self.slider.set(self.cursor)
        self._render()

    def prev_step(self):
        if not self.game:
            return
        self.cursor = max(0, self.cursor - 1)
        self.slider.set(self.cursor)
        self._render()

    def next_step(self):
        if not self.game:
            return
        self.cursor = min(len(self.moves), self.cursor + 1)
        self.slider.set(self.cursor)
        self._render()

    def _render(self):
        if not self.game:
            return

        total = len(self.moves)
        self.step_lbl.config(text=f"{self.cursor}/{total}")

        board = [[EMPTY for _ in range(self.cols)] for _ in range(self.rows)]
        for i in range(min(self.cursor, total)):
            mv = self.moves[i]
            board[int(mv["row"])][int(mv["col"])] = mv["color"]

        seq = str(self.game.get("original_sequence") or "")
        canon = str(self.game.get("canonical_key") or "")
        status = self.game.get("status")
        winner = self.game.get("winner")
        draw = bool(self.game.get("draw"))
        start = self.game.get("starting_color")
        src = self.game.get("source_filename")

        mir_seq = ""
        if seq and hasattr(db, "mirror_sequence"):
            try:
                mir_seq = db.mirror_sequence(seq, self.cols)
            except Exception:
                mir_seq = ""

        if bool(self.show_mirror.get()):
            board = self._mirror_board(board)

        info = f"#{self.game_id} | status={status} | start={start}"
        if winner:
            info += f" | winner={winner}"
        if draw:
            info += " | draw=True"
        if src:
            info += f" | src={src}"
        info += f" | step={self.cursor}/{total}"
        info += f" | seq={seq} | canon={canon}"
        if mir_seq:
            info += f" | miroir_seq={mir_seq}"
        self.info.config(text=info)

        m, s = self.margin, self.cell
        w = m * 2 + self.cols * s
        h = m * 2 + self.rows * s
        self.canvas.config(width=w, height=h)
        self.canvas.delete("all")

        self.canvas.create_rectangle(
            m, m, m + self.cols * s, m + self.rows * s, fill=BOARD_BG, outline=BOARD_BG
        )

        for r in range(self.rows):
            for c in range(self.cols):
                x1 = m + c * s + 6
                y1 = m + r * s + 6
                x2 = m + (c + 1) * s - 6
                y2 = m + (r + 1) * s - 6
                val = board[r][c]
                self.canvas.create_oval(
                    x1, y1, x2, y2, fill=COLOR_FILL[val], outline=OUTLINE, width=2
                )

    def _mirror_board(self, board):
        out = [[EMPTY for _ in range(self.cols)] for _ in range(self.rows)]
        for r in range(self.rows):
            for c in range(self.cols):
                out[r][self.cols - 1 - c] = board[r][c]
        return out


if __name__ == "__main__":
    Viewer().mainloop()
