# view_tk.py
# Vue Tkinter (widgets + rendu + événements UI)

import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import List, Optional, Dict, Any, Tuple

from core import COLOR_FILL, COLOR_NAME, RED, YELLOW, EMPTY, CONFIG_PATH

# ----------------------------
# THEME (couleurs UI)
# ----------------------------

WINDOW_BG = "#0f172a"
FRAME_BG = "#111827"
TEXT_FG = "#e5e7eb"

BTN_BG = "#2563eb"
BTN_FG = "#ffffff"
BTN_HOVER = "#1d4ed8"
BTN_DIS = "#334155"

ACCENT = "#22c55e"

BOARD_BG = "#1565c0"
COLOR_OUTLINE = "#263238"
HILITE = "#00e676"


class TkView(tk.Tk):
    """
    Vue pure: construit l'UI, affiche, et relaie les événements vers le Controller.
    La Vue NE modifie PAS le modèle.
    """

    def __init__(self):
        super().__init__()
        self.title("Puissance 4 — Tkinter")
        self.configure(bg=WINDOW_BG)

        self.controller = None  # type: ignore

        # dimensions dynamiques
        self.cell = 64
        self.margin = 18
        self.delay_ms = 250
        self.rows = 8
        self.cols = 9
        self.top_pad = 34
        self.bottom_pad = 40

        # state UI affichage
        self._ai_scores: List[Optional[int]] = []
        self._thinking = False

        self._setup_style()
        self._build_ui()

    # ---------- Controller hook ----------
    def set_controller(self, controller) -> None:
        self.controller = controller
        self.protocol("WM_DELETE_WINDOW", self.controller.on_close)

    # ---------- getters ----------
    def get_mode(self) -> int:
        return int(self.mode_cb.current())

    def set_mode(self, idx: int) -> None:
        self.mode_cb.current(int(idx))

    def get_algo(self) -> str:
        return str(self.robot_algo.get())

    def get_depth(self) -> int:
        try:
            return int(self.depth_var.get() or 3)
        except Exception:
            return 3

    # ---------- UI plumbing ----------
    def _setup_style(self):
        style = ttk.Style(self)

        for theme_try in ("clam", "alt", "default"):
            try:
                style.theme_use(theme_try)
                break
            except Exception:
                pass

        style.configure(".", font=("Segoe UI", 10))
        style.configure("Custom.TFrame", background=FRAME_BG)
        style.configure("Custom.TLabel", background=FRAME_BG, foreground=TEXT_FG)

        style.configure(
            "Custom.TButton",
            padding=10,
            relief="flat",
            background=BTN_BG,
            foreground=BTN_FG,
        )
        style.map(
            "Custom.TButton",
            background=[("active", BTN_HOVER), ("disabled", BTN_DIS)],
            foreground=[("active", BTN_FG), ("disabled", "#94a3b8")],
        )

        style.configure("Custom.TCombobox", padding=6)
        style.configure(
            "Custom.Horizontal.TScale", troughcolor="#1f2937", background=ACCENT
        )

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        root = ttk.Frame(self, padding=12, style="Custom.TFrame")
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        top = ttk.Frame(root, style="Custom.TFrame")
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(99, weight=1)

        ttk.Label(top, text="Mode :", style="Custom.TLabel").grid(
            row=0, column=0, padx=(0, 8)
        )

        self.mode_cb = ttk.Combobox(
            top,
            state="readonly",
            values=[
                "0 joueur (robot vs robot)",
                "1 joueur (humain vs robot)",
                "2 joueurs (humain vs humain)",
            ],
            width=26,
            style="Custom.TCombobox",
        )
        self.mode_cb.current(2)
        self.mode_cb.grid(row=0, column=1, padx=(0, 12))
        self.mode_cb.bind(
            "<<ComboboxSelected>>", lambda e: self.controller.on_mode_change()
        )

        ttk.Label(top, text="Robot :", style="Custom.TLabel").grid(
            row=0, column=2, padx=(0, 6)
        )
        self.robot_algo = tk.StringVar(value="Random")
        self.robot_cb = ttk.Combobox(
            top,
            state="readonly",
            values=["Random", "MiniMax"],
            width=8,
            textvariable=self.robot_algo,
            style="Custom.TCombobox",
        )
        self.robot_cb.grid(row=0, column=3, padx=(0, 12))
        self.robot_cb.bind(
            "<<ComboboxSelected>>", lambda e: self.controller.on_robot_change()
        )

        ttk.Label(top, text="Profondeur :", style="Custom.TLabel").grid(
            row=0, column=4, padx=(0, 6)
        )
        self.depth_var = tk.IntVar(value=3)
        self.depth_spin = ttk.Spinbox(
            top, from_=1, to=8, width=4, textvariable=self.depth_var
        )
        self.depth_spin.grid(row=0, column=5, padx=(0, 12))
        self.depth_spin.bind(
            "<KeyRelease>", lambda e: self.controller.on_robot_change()
        )

        ttk.Button(
            top,
            text="Nouveau",
            command=lambda: self.controller.on_new_game(),
            style="Custom.TButton",
        ).grid(row=0, column=6, padx=6)
        self.btn_pause = ttk.Button(
            top,
            text="Pause",
            command=lambda: self.controller.on_toggle_pause(),
            style="Custom.TButton",
        )
        self.btn_pause.grid(row=0, column=7, padx=6)

        ttk.Button(
            top,
            text="↩ Précédent",
            command=lambda: self.controller.on_undo(),
            style="Custom.TButton",
        ).grid(row=0, column=8, padx=6)
        ttk.Button(
            top,
            text="↪ Suivant",
            command=lambda: self.controller.on_redo(),
            style="Custom.TButton",
        ).grid(row=0, column=9, padx=6)

        ttk.Button(
            top,
            text="Sauvegarder",
            command=lambda: self.controller.on_save_json(),
            style="Custom.TButton",
        ).grid(row=0, column=10, padx=6, sticky="w")
        ttk.Button(
            top,
            text="Charger",
            command=lambda: self.controller.on_load_json(),
            style="Custom.TButton",
        ).grid(row=0, column=11, padx=6)

        ttk.Button(
            top,
            text="Charger DB",
            command=lambda: self.controller.on_load_db_popup(),
            style="Custom.TButton",
        ).grid(row=0, column=12, padx=6)
        ttk.Button(
            top,
            text="⚙ Réglages",
            command=lambda: self.controller.on_open_settings(),
            style="Custom.TButton",
        ).grid(row=0, column=13, padx=(6, 0), sticky="e")

        mid = ttk.Frame(root, style="Custom.TFrame")
        mid.grid(row=1, column=0, sticky="nsew", pady=12)
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(0, weight=1)

        w = self.margin * 2 + self.cols * self.cell
        h = self.top_pad + self.margin * 2 + self.rows * self.cell + self.bottom_pad

        self.canvas = tk.Canvas(
            mid, width=w, height=h, bg=FRAME_BG, highlightthickness=0
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        bottom = ttk.Frame(root, style="Custom.TFrame")
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(1, weight=1)

        self.status = ttk.Label(bottom, text="", anchor="w", style="Custom.TLabel")
        self.status.grid(row=0, column=0, sticky="w")

        self.slider = ttk.Scale(
            bottom,
            from_=0,
            to=0,
            orient="horizontal",
            command=lambda v: self.controller.on_slider(v),
            style="Custom.Horizontal.TScale",
        )
        self.slider.grid(row=0, column=1, sticky="ew", padx=12)

        self.step_label = ttk.Label(bottom, text="0/0", style="Custom.TLabel")
        self.step_label.grid(row=0, column=2, sticky="e")

    # ---------- Events ----------
    def _on_canvas_click(self, event):
        if self.controller:
            self.controller.on_canvas_click(event.x, event.y)

    # ---------- Rendering ----------
    def resize_canvas(
        self, rows: int, cols: int, cell: int, margin: int, delay_ms: int
    ):
        self.rows = rows
        self.cols = cols
        self.cell = cell
        self.margin = margin
        self.delay_ms = delay_ms

        w = self.margin * 2 + self.cols * self.cell
        h = self.top_pad + self.margin * 2 + self.rows * self.cell + self.bottom_pad
        self.canvas.config(width=w, height=h)

    def render(
        self,
        board: List[List[str]],
        winning_line: Optional[List[Tuple[int, int]]],
        ai_scores: List[Optional[int]],
        thinking: bool,
        status_text: str,
        cursor: int,
        total: int,
        paused: bool,
    ):
        self._ai_scores = ai_scores
        self._thinking = thinking

        # canvas
        self.canvas.delete("all")
        rows, cols = self.rows, self.cols
        m, s = self.margin, self.cell
        y0 = self.top_pad

        for c in range(cols):
            cx = m + c * s + s / 2
            self.canvas.create_text(
                cx, y0 / 2, text=str(c + 1), fill=TEXT_FG, font=("Segoe UI", 11, "bold")
            )

        self.canvas.create_rectangle(
            m, y0 + m, m + cols * s, y0 + m + rows * s, fill=BOARD_BG, outline=BOARD_BG
        )

        winning = set(winning_line or [])
        for r in range(rows):
            for c in range(cols):
                x1 = m + c * s + 6
                y1 = y0 + m + r * s + 6
                x2 = m + (c + 1) * s - 6
                y2 = y0 + m + (r + 1) * s - 6

                val = board[r][c]
                fill = COLOR_FILL[val]
                outline = HILITE if (r, c) in winning else COLOR_OUTLINE
                width = 5 if (r, c) in winning else 2
                self.canvas.create_oval(
                    x1, y1, x2, y2, fill=fill, outline=outline, width=width
                )

        base_y = y0 + m + rows * s + 18
        for c in range(cols):
            cx = m + c * s + s / 2
            sc = ai_scores[c] if c < len(ai_scores) else None
            txt = "—" if sc is None else str(sc)
            self.canvas.create_text(
                cx, base_y, text=txt, fill=TEXT_FG, font=("Segoe UI", 10)
            )

        if thinking:
            self.canvas.create_text(
                m + 6,
                y0 + 6,
                text="Réflexion MiniMax...",
                fill=TEXT_FG,
                anchor="nw",
                font=("Segoe UI", 10, "italic"),
            )

        # status + slider
        self.status.config(text=status_text)
        self.btn_pause.config(text="Reprendre" if paused else "Pause")

        self.slider.configure(to=total)
        self.slider.set(cursor)
        self.step_label.config(text=f"{cursor}/{total}")

    # ---------- Dialog helpers ----------
    def ask_save_path(self, initialdir: str, initialfile: str) -> str:
        return (
            filedialog.asksaveasfilename(
                initialdir=initialdir,
                initialfile=initialfile,
                defaultextension=".json",
                filetypes=[("JSON", "*.json")],
            )
            or ""
        )

    def ask_load_path(self, initialdir: str) -> str:
        return (
            filedialog.askopenfilename(
                initialdir=initialdir, filetypes=[("JSON", "*.json")]
            )
            or ""
        )

    def info(self, title: str, msg: str) -> None:
        messagebox.showinfo(title, msg)

    def error(self, title: str, msg: str) -> None:
        messagebox.showerror(title, msg)

    def ask_db_choice(self, rows: List[Dict[str, Any]]) -> Optional[int]:
        win = tk.Toplevel(self)
        win.title("Charger une partie depuis la DB")
        win.transient(self)
        win.grab_set()

        # Layout
        frm = ttk.Frame(win, padding=12, style="Custom.TFrame")
        frm.grid(row=0, column=0, sticky="nsew")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)

        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(0, weight=1)

        # --- Tableau ---
        columns = ("id", "status", "seq", "winner", "draw", "src")

        tree = ttk.Treeview(frm, columns=columns, show="headings", height=16)
        tree.grid(row=0, column=0, sticky="nsew")

        vsb = ttk.Scrollbar(frm, orient="vertical", command=tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=vsb.set)

        hsb = ttk.Scrollbar(frm, orient="horizontal", command=tree.xview)
        hsb.grid(row=1, column=0, sticky="ew")
        tree.configure(xscrollcommand=hsb.set)

        # Titres colonnes
        tree.heading("id", text="ID")
        tree.heading("status", text="Status")
        tree.heading("seq", text="Seq")
        tree.heading("winner", text="Winner")
        tree.heading("draw", text="Draw")
        tree.heading("src", text="Source")

        # Largeurs (ajuste si tu veux)
        tree.column("id", width=70, anchor="center", stretch=False)
        tree.column("status", width=120, anchor="center", stretch=False)
        tree.column("seq", width=260, anchor="w", stretch=True)
        tree.column("winner", width=90, anchor="center", stretch=False)
        tree.column("draw", width=80, anchor="center", stretch=False)
        tree.column("src", width=320, anchor="w", stretch=True)
        # Tri par ID décroissant (plus grand ID en haut)
        
        rows = sorted(rows, key=lambda r: int(r.get("id", 0)), reverse=True)

        # Remplissage
        for gg in rows:
            gid = gg.get("id", "")
            status = gg.get("status", "")
            seq = str(gg.get("original_sequence") or "")
            winner = gg.get("winner") or ""
            draw = "True" if gg.get("draw") else ""
            src = str(gg.get("source_filename") or "")

            tree.insert("", "end", values=(gid, status, seq, winner, draw, src))

        # Selection
        chosen: Dict[str, Optional[int]] = {"id": None}

        def do_load():
            sel = tree.selection()
            if not sel:
                return
            vals = tree.item(sel[0], "values")
            # vals[0] = id
            try:
                chosen["id"] = int(vals[0])
            except Exception:
                chosen["id"] = None
            win.destroy()

        def do_cancel():
            win.destroy()

        def on_double_click(_evt=None):
            do_load()

        tree.bind("<Double-1>", on_double_click)

        # Buttons
        btns = ttk.Frame(frm, style="Custom.TFrame")
        btns.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)

        ttk.Button(btns, text="Charger", command=do_load, style="Custom.TButton").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(
            btns, text="Annuler", command=do_cancel, style="Custom.TButton"
        ).grid(row=0, column=1, sticky="e")

        # Focus par défaut
        if tree.get_children():
            first = tree.get_children()[0]
            tree.selection_set(first)
            tree.focus(first)

        self.wait_window(win)
        return chosen["id"]

    def open_settings_dialog(self, cfg: Dict[str, Any], on_save):
        win = tk.Toplevel(self)
        win.title("Paramètres (config.json)")
        win.configure(bg=WINDOW_BG)
        win.transient(self)
        win.grab_set()

        frm = ttk.Frame(win, padding=12, style="Custom.TFrame")
        frm.grid(row=0, column=0, sticky="nsew")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)

        rows_var = tk.IntVar(value=int(cfg["rows"]))
        cols_var = tk.IntVar(value=int(cfg["cols"]))
        start_var = tk.StringVar(value=str(cfg["starting_color"]))
        cell_var = tk.IntVar(value=int(cfg["cell_size"]))
        margin_var = tk.IntVar(value=int(cfg["margin"]))
        delay_var = tk.IntVar(value=int(cfg["drop_delay_ms"]))

        def row(label, widget, r):
            ttk.Label(frm, text=label, style="Custom.TLabel").grid(
                row=r, column=0, sticky="w", pady=6, padx=(0, 10)
            )
            widget.grid(row=r, column=1, sticky="ew", pady=6)

        row("Lignes (>=4):", ttk.Spinbox(frm, from_=4, to=30, textvariable=rows_var), 0)
        row(
            "Colonnes (>=4):",
            ttk.Spinbox(frm, from_=4, to=30, textvariable=cols_var),
            1,
        )

        cb = ttk.Combobox(
            frm,
            state="readonly",
            values=[RED, YELLOW],
            textvariable=start_var,
            style="Custom.TCombobox",
        )
        row("Couleur qui commence (R/Y):", cb, 2)

        row(
            "Taille cellule (30..120):",
            ttk.Spinbox(frm, from_=30, to=120, textvariable=cell_var),
            3,
        )
        row(
            "Marge (5..50):",
            ttk.Spinbox(frm, from_=5, to=50, textvariable=margin_var),
            4,
        )
        row(
            "Délai auto (ms):",
            ttk.Spinbox(frm, from_=0, to=2000, textvariable=delay_var),
            5,
        )

        btns = ttk.Frame(frm, style="Custom.TFrame")
        btns.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))

        def save_and_close():
            new_cfg = {
                "rows": max(4, min(int(rows_var.get()), 30)),
                "cols": max(4, min(int(cols_var.get()), 30)),
                "starting_color": (
                    start_var.get() if start_var.get() in (RED, YELLOW) else RED
                ),
                "cell_size": max(30, min(int(cell_var.get()), 120)),
                "margin": max(5, min(int(margin_var.get()), 50)),
                "drop_delay_ms": max(0, min(int(delay_var.get()), 2000)),
            }
            try:
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(new_cfg, f, indent=2, ensure_ascii=False)
                on_save(new_cfg)
                win.destroy()
            except Exception as e:
                self.error("Erreur", f"Impossible d'écrire config.json:\n{e}")

        ttk.Button(
            btns, text="Annuler", command=win.destroy, style="Custom.TButton"
        ).grid(row=0, column=0, padx=6)
        ttk.Button(
            btns, text="Enregistrer", command=save_and_close, style="Custom.TButton"
        ).grid(row=0, column=1, padx=6)
