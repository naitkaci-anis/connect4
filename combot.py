"""
combot.py  —  Bot BGA Puissance 4 avec IA
==========================================
Améliorations vs version random :
  1. Détecte qui commence (nous ou l'adversaire)
  2. Lit les coups adversaires en temps réel depuis le DOM BGA
  3. Utilise ai_engine.py pour choisir les meilleurs coups
  4. Synchronise le plateau local avec l'état réel BGA à chaque tour

Corrections v2 :
  FIX 1 — Reconnexion automatique si déconnecté de BGA
  FIX 2 — Détection couleur fiable (player_boards CSS + 1er coup des logs)
  FIX 3 — Détection premier joueur fiable (attend 1er coup log, pas possibleMove)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Cherche ai_engine dans le dossier courant ou dans web_backend
_HERE = Path(__file__).resolve().parent
for _p in [_HERE, _HERE / "web_backend"]:
    if (_p / "ai_engine.py").exists():
        sys.path.insert(0, str(_p))
        break

import time
import re
from typing import Optional, Dict, List, Tuple

from selenium import webdriver
from selenium.common.exceptions import WebDriverException, StaleElementReferenceException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import db
from core import Connect4, RED, YELLOW, EMPTY
from ai_engine import ai_choose_column_from_game


# ============================================================
# CONFIG
# ============================================================

BASE       = "https://boardgamearena.com"
GAME_NAME  = "connectfour"

CONFIANCE       = 5          # parties jouées par le bot = haute confiance
POLL_SECONDS    = 1.0        # intervalle de polling
AFTER_MOVE_WAIT = 1.5        # attente après notre coup
AFTER_GAME_WAIT = 8.0        # attente entre les parties
AI_DEPTH        = 7          # profondeur minimax

HEADLESS               = False
USE_PERSISTENT_PROFILE = True

PROJECT_DIR       = Path(__file__).resolve().parent
CHROME_PROFILE_DIR = PROJECT_DIR / "chrome_profile_bga"
CHROME_PROFILE_DIR.mkdir(exist_ok=True)


# ============================================================
# LOGS
# ============================================================

def banner(msg: str):
    print("\n" + "=" * 72)
    print(msg)
    print("=" * 72)

def log(msg: str):
    print(f"[combot] {msg}")


# ============================================================
# DRIVER
# ============================================================

def make_driver(headless: bool = HEADLESS) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1400,1000")
    else:
        opts.add_argument("--start-maximized")

    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=fr-FR")

    if USE_PERSISTENT_PROFILE:
        opts.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
        opts.add_argument("--profile-directory=Default")

    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(60)
    return driver


# ============================================================
# LECTURE DU PLATEAU BGA
# ============================================================

def read_board_from_dom(driver, rows: int, cols: int) -> Optional[List[List[str]]]:
    """
    Lit le plateau depuis le DOM BGA.

    Structure réelle :
      <div id="square_COL_ROW" class="square ...">
        <div class="disc disccolor_ff0000"></div>   <- Rouge
        <div class="disc disccolor_ffff00"></div>   <- Jaune
      </div>
    COL et ROW sont 1-based.
    """
    try:
        board = [[EMPTY] * cols for _ in range(rows)]
        squares = driver.find_elements(By.CSS_SELECTOR, "#board .square")

        for sq in squares:
            try:
                sq_id = (sq.get_attribute("id") or "").strip()
            except StaleElementReferenceException:
                continue

            m = re.match(r"^square_(\d+)_(\d+)$", sq_id)
            if not m:
                continue

            bga_col = int(m.group(1))
            bga_row = int(m.group(2))
            col0    = bga_col - 1
            row0    = bga_row - 1

            if not (0 <= col0 < cols and 0 <= row0 < rows):
                continue

            try:
                for disc in sq.find_elements(By.CSS_SELECTOR, ".disc"):
                    disc_cls = disc.get_attribute("class") or ""
                    if "disccolor_ff0000" in disc_cls:    # Rouge  #ff0000
                        board[row0][col0] = RED
                        break
                    elif "disccolor_ffff00" in disc_cls:  # Jaune  #ffff00
                        board[row0][col0] = YELLOW
                        break
            except StaleElementReferenceException:
                continue

        return board

    except Exception as e:
        log(f"read_board_from_dom erreur: {e}")
        return None


def boards_equal(a: List[List[str]], b: List[List[str]]) -> bool:
    return all(a[r][c] == b[r][c] for r in range(len(a)) for c in range(len(a[0])))


def find_new_move(old_board: List[List[str]],
                  new_board: List[List[str]],
                  rows: int, cols: int) -> Optional[Tuple[int, int]]:
    """
    Trouve la case qui a changé entre old_board et new_board.
    Retourne (row0, col0) en 0-based, ou None.
    """
    for r in range(rows):
        for c in range(cols):
            if old_board[r][c] == EMPTY and new_board[r][c] != EMPTY:
                return r, c
    return None


# ============================================================
# LECTURE LOGS BGA
# Format : "mgaddini place un pion dans la colonne 3"
# ============================================================

def read_log_moves(driver) -> List[Tuple[str, int]]:
    """
    Lit les coups depuis les logs BGA.
    Retourne [(nom_joueur, colonne_1based), ...] du plus récent au plus ancien.
    """
    result = []
    try:
        log_els = driver.find_elements(By.CSS_SELECTOR, "#logs .log_replayable")
        for el in log_els:
            try:
                text = (el.text or "").strip()
                m = re.search(
                    r"^(.+?)\s+place\s+un\s+pion\s+dans\s+la\s+colonne\s+(\d+)",
                    text, re.IGNORECASE
                )
                if m:
                    result.append((m.group(1).strip(), int(m.group(2))))
            except StaleElementReferenceException:
                continue
    except Exception:
        pass
    return result


# ============================================================
# BOT IA
# ============================================================

class BGAIACombot:

    def __init__(self):
        self.driver = make_driver()
        self.wait   = WebDriverWait(self.driver, 20)

        self.match_counter = 0
        self.local_game   : Optional[Connect4] = None
        self.current_source: Optional[str]     = None

        # Notre couleur dans la partie en cours
        self.my_color    : Optional[str] = None
        self.their_color : Optional[str] = None

        # Notre pseudo BGA (lu à la connexion)
        self.my_name: Optional[str] = None

        # Nombre de coups logs déjà appliqués localement
        self._n_log_applied: int = 0

        # Dernier plateau lu depuis le DOM
        self.last_known_board: Optional[List[List[str]]] = None

    # ----------------------------------------------------------
    # Navigation
    # ----------------------------------------------------------

    def login(self):
        banner("Connexion BGA")
        self.driver.get(f"{BASE}/account")
        log("Connecte-toi manuellement si besoin.")
        input("Quand tu es connecté, appuie sur Entrée... ")
        log(f"URL actuelle: {self.driver.current_url}")
        # FIX 2 : récupérer notre pseudo dès la connexion
        self.my_name = self._fetch_my_name()
        log(f"Pseudo détecté : {self.my_name or '(non trouvé)'}")

    def _fetch_my_name(self) -> Optional[str]:
        """FIX 2 : lit notre pseudo depuis le header BGA."""
        for sel in [
            "#head_infoperso .player-name",
            "#head_infoperso span.playername",
            ".header_infoperso .playername",
            "#overall_user_infos .playername",
        ]:
            try:
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    name = (el.text or "").strip()
                    if name:
                        return name
            except Exception:
                pass
        return None

    def navigate_to_game(self):
        url = f"{BASE}/gamepanel?game={GAME_NAME}"
        log(f"Navigation vers {url}")
        self.driver.get(url)

    def clear_popups(self):
        try:
            for popup in self.driver.find_elements(By.CSS_SELECTOR, "div[id^='continue_btn_']"):
                if popup.is_displayed():
                    log("Popup détecté, fermeture...")
                    self.driver.execute_script("arguments[0].click();", popup)
                    time.sleep(1)
        except Exception:
            pass

    def select_realtime_mode(self):
        log("Sélection du mode Temps Réel...")
        while True:
            self.clear_popups()
            try:
                btn = self.wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, ".panel-block--buttons__mode-select .bga-dropdown-button")
                ))
                if "TEMPS RÉEL" in (btn.text or "").upper():
                    log("Mode Temps Réel confirmé.")
                    return
                self.driver.execute_script("arguments[0].click();", btn)
                time.sleep(1.0)
                opt = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".bga-dropdown-option-realtime"))
                )
                self.driver.execute_script("arguments[0].click();", opt)
                time.sleep(1.5)
            except Exception:
                time.sleep(2)

    def start_table(self) -> bool:
        """
        Clique sur Jouer, attend adversaire, accepte, attend le plateau.
        """
        log("Recherche adversaire et démarrage de partie...")

        # Cliquer sur le bouton "Jouer" pour lancer la recherche
        self._click_play_now()
        time.sleep(2)

        for _ in range(120):
            self.clear_popups()
            try:
                # Partie démarrée → plateau visible
                if self.driver.find_elements(By.ID, "board"):
                    log("Plateau détecté, partie démarrée.")
                    return True

                # Adversaire trouvé → accepter
                accept = self.driver.find_elements(By.ID, "ags_start_game_accept")
                if accept and accept[0].is_displayed():
                    log("Adversaire trouvé → Accepter")
                    self.driver.execute_script("arguments[0].click();", accept[0])
                    time.sleep(2)
                    continue

                # Bouton Démarrer (si on est l'hôte de table)
                for txt in ["Démarrer", "Demarrer", "Start"]:
                    starts = self.driver.find_elements(By.XPATH,
                        f"//a[contains(@class,'bga-button')]//div[contains(text(),'{txt}')]")
                    starts = [s for s in starts if s.is_displayed()]
                    if starts:
                        log(f"Clic sur '{txt}'")
                        self.driver.execute_script("arguments[0].click();", starts[0])
                        time.sleep(2)
                        break

                time.sleep(2)

            except WebDriverException as e:
                log(f"start_table erreur ({e}), retry...")
                time.sleep(2)
            except Exception:
                time.sleep(2)

        return False

    def _click_play_now(self):
        """Clique sur le bouton 'Jouer' pour lancer la recherche d'adversaire."""
        for sel in [
            ".panel-block--buttons .bga-button--primary",
            ".panel-block--buttons .bga-button",
            "#join_table_btn",
            ".joinnow",
        ]:
            try:
                els = [e for e in self.driver.find_elements(By.CSS_SELECTOR, sel)
                       if e.is_displayed()]
                if els:
                    log(f"Clic Jouer ({sel})")
                    self.driver.execute_script("arguments[0].click();", els[0])
                    return
            except Exception:
                pass
        for sel in ["//button[contains(text(),'Jouer')]",
                    "//a[contains(text(),'Jouer')]"]:
            try:
                els = [e for e in self.driver.find_elements(By.XPATH, sel)
                       if e.is_displayed()]
                if els:
                    log("Clic Jouer (xpath)")
                    self.driver.execute_script("arguments[0].click();", els[0])
                    return
            except Exception:
                pass
        log("Bouton Jouer non trouvé — partie peut-être déjà en cours.")

    # ----------------------------------------------------------
    # FIX 1 : Reconnexion automatique
    # ----------------------------------------------------------

    def is_logged_in(self) -> bool:
        """
        FIX 1 : vérifie que la session BGA est active.
        En cours de partie, le header n'est PAS visible → ne pas checker le DOM.
        On est connecté si l'URL est sur BGA et n'est pas une page de login.
        """
        try:
            url = self.driver.current_url or ""
            # Redirigé vers login = déconnecté
            if "login" in url:
                return False
            # Pas sur BGA = problème réseau
            if "boardgamearena.com" not in url:
                return False
            # En cours de partie = forcément connecté
            if "connectfour" in url or "gameui" in url or "table=" in url:
                return True
            # Sur une autre page BGA → vérifier le header
            els = self.driver.find_elements(
                By.CSS_SELECTOR, "#head_infoperso, .header_infoperso, #overall_user_infos"
            )
            return len(els) > 0
        except Exception:
            return True  # en cas de doute on ne coupe pas

    def is_still_in_game(self) -> bool:
        try:
            url = self.driver.current_url or ""
            return "connectfour" in url or "gameui" in url
        except Exception:
            return False

    def reconnect(self):
        """FIX 1 : tente de restaurer la session si déconnecté."""
        log("Session perdue, tentative reconnexion...")
        try:
            self.driver.get(f"{BASE}/account")
            time.sleep(3)
            if "login" in self.driver.current_url.lower():
                log("Reconnexion manuelle requise.")
                input("Reconnecte-toi sur BGA puis appuie sur Entrée... ")
            else:
                log("Session restaurée automatiquement.")
            self.my_name = self._fetch_my_name() or self.my_name
        except Exception as e:
            log(f"Reconnexion échouée: {e}")

    def find_active_game(self) -> bool:
        """FIX 1 : cherche et rejoint une partie connectfour en cours."""
        try:
            self.driver.get(f"{BASE}/gameinprogress")
            time.sleep(2)
            for lnk in self.driver.find_elements(By.CSS_SELECTOR, "a[href*='connectfour']"):
                href = lnk.get_attribute("href") or ""
                if "table=" in href:
                    log(f"Partie active trouvée: {href}")
                    self.driver.get(href)
                    time.sleep(3)
                    if self.driver.find_elements(By.ID, "board"):
                        return True
        except Exception as e:
            log(f"find_active_game erreur: {e}")
        return False

    # ----------------------------------------------------------
    # FIX 2 & 3 : Détection couleur et premier joueur fiables
    # ----------------------------------------------------------

    def detect_my_color(self) -> str:
        """
        FIX 2 & 3 : Détecte notre couleur de façon fiable.

        Méthode 1 — #player_boards (couleur CSS du pseudo) :
          Rouge = color:#ff0000,  Jaune = color:#ffff00

        Méthode 2 — Attendre le 1er coup dans les logs BGA :
          Si le 1er coup est de nous → on est Rouge (on commence).
          Si le 1er coup est de l'adversaire → on est Jaune.
          → 100% fiable, évite le faux-positif de possibleMove.

        Méthode 3 — Fallback possibleMove (dernier recours).
        """
        log("Détection de notre couleur (qui commence)...")

        # Méthode 1 : #player_boards
        color = self._color_from_player_boards()
        if color:
            log(f"Couleur via player_boards: {color}")
            return color

        # Méthode 2 : attendre le 1er coup dans les logs (max 20s)
        log("Attente 1er coup pour détecter la couleur (max 20s)...")
        for _ in range(20):
            time.sleep(1)
            log_moves = read_log_moves(self.driver)
            if log_moves:
                # log_moves[-1] = plus ancien = 1er coup joué depuis le début
                first_name, _ = log_moves[-1]
                if self.my_name and first_name.lower() == self.my_name.lower():
                    log(f"1er coup = nous ({first_name}) → ROUGE")
                    return RED
                else:
                    log(f"1er coup = adversaire ({first_name}) → JAUNE")
                    return YELLOW

        # Méthode 3 : possibleMove visible (fallback)
        log("Fallback possibleMove...")
        for _ in range(6):
            try:
                body_cls = self.driver.find_element(
                    By.TAG_NAME, "body").get_attribute("class") or ""
                possibles = self.driver.find_elements(
                    By.CSS_SELECTOR, "#board .square.possibleMove")
                possibles = [p for p in possibles if p.is_displayed()]
                if "current_player_is_active" in body_cls or len(possibles) > 0:
                    log("possibleMove visible → ROUGE")
                    return RED
            except Exception:
                pass
            time.sleep(1)

        log("Aucune détection → JAUNE par défaut")
        return YELLOW

    def _color_from_player_boards(self) -> Optional[str]:
        """FIX 2 : lit la couleur de notre pseudo dans #player_boards."""
        if not self.my_name:
            return None
        for sel in [
            "#player_boards .playername",
            "#player_boards .player-name",
            ".player_board .playername",
        ]:
            try:
                for span in self.driver.find_elements(By.CSS_SELECTOR, sel):
                    name = (span.text or "").strip()
                    if name.lower() != self.my_name.lower():
                        continue
                    style = (span.get_attribute("style") or "").lower().replace(" ", "")
                    if "color:#ff0000" in style:
                        return RED
                    if "color:#ffff00" in style:
                        return YELLOW
            except Exception:
                pass
        return None

    def _get_my_player_name(self) -> Optional[str]:
        """Récupère notre nom depuis #player_boards (fallback)."""
        try:
            panels = self.driver.find_elements(
                By.CSS_SELECTOR, "#player_boards .player-name, #player_boards .playername"
            )
            if panels:
                return (panels[0].text or "").strip()
        except Exception:
            pass
        return None

    def _get_player_color_from_logs(self, player_name: str) -> Optional[str]:
        """
        Lit les logs BGA et trouve la couleur associée à un nom de joueur.
        Structure : <span class="playername" style="color:#ff0000;">mgaddini</span>
        """
        try:
            spans = self.driver.find_elements(
                By.CSS_SELECTOR, "#logs .playername, #chatlogs .playername"
            )
            for span in spans:
                name = (span.text or "").strip()
                if name.lower() != player_name.lower():
                    continue
                style = (span.get_attribute("style") or "").lower()
                if "color:#ff0000" in style or "color: #ff0000" in style:
                    return RED
                if "color:#ffff00" in style or "color: #ffff00" in style:
                    return YELLOW
        except Exception:
            pass
        return None

    def _read_last_log_move(self) -> Optional[int]:
        """
        Lit le dernier coup depuis les logs BGA.
        Retourne le numéro de colonne 1-based ou None.
        """
        try:
            logs = self.driver.find_elements(By.CSS_SELECTOR, "#logs .log_replayable")
            if not logs:
                return None
            text = (logs[0].text or "").strip()
            m = re.search(r"colonne\s+(\d+)", text, re.IGNORECASE)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return None

    # ----------------------------------------------------------
    # Plateau local
    # ----------------------------------------------------------

    def detect_board_size(self) -> Tuple[int, int]:
        try:
            squares = self.driver.find_elements(By.CSS_SELECTOR, "#board .square")
            max_col = max_row = 0
            for sq in squares:
                m = re.match(r"^square_(\d+)_(\d+)$", sq.get_attribute("id") or "")
                if m:
                    max_col = max(max_col, int(m.group(1)))
                    max_row = max(max_row, int(m.group(2)))
            if max_col > 0 and max_row > 0:
                return max_row, max_col
        except Exception:
            pass
        return 6, 7

    def start_new_local_match(self):
        self.match_counter += 1
        rows, cols = self.detect_board_size()

        self.my_color    = self.detect_my_color()
        self.their_color = YELLOW if self.my_color == RED else RED

        # BGA : Rouge commence toujours (starting_color = RED)
        self.local_game = Connect4(rows, cols, RED)

        self.current_source  = f"bga_bot_ia_{int(time.time())}_{self.match_counter}"
        self.last_known_board = [[EMPTY] * cols for _ in range(rows)]
        self._n_log_applied   = 0

        log(f"Partie #{self.match_counter} | taille={rows}x{cols} | "
            f"nous={self.my_color} | eux={self.their_color}")

    def _resync_full_board(self):
        """Relit le plateau complet depuis BGA et reconstruit local_game."""
        rows, cols = self.detect_board_size()
        dom_board  = read_board_from_dom(self.driver, rows, cols)
        if dom_board is None:
            return False
        r_count = sum(c == RED    for row in dom_board for c in row)
        y_count = sum(c == YELLOW for row in dom_board for c in row)
        game = Connect4(rows, cols, RED)
        game.board        = [row[:] for row in dom_board]
        game.cursor       = r_count + y_count
        game.current_turn = RED if r_count == y_count else YELLOW
        if self.local_game:
            game.mode = self.local_game.mode
        # Détecter victoire existante
        for rr in range(rows):
            for cc in range(cols):
                color = dom_board[rr][cc]
                if color == EMPTY:
                    continue
                line = game.check_winner_from(rr, cc, color)
                if line:
                    game.finished    = True
                    game.winner      = color
                    game.winning_line = line
        self.local_game = game
        log(f"Resync: R={r_count} Y={y_count} tour={game.current_turn}")
        return True

    # ----------------------------------------------------------
    # Lecture des coups adversaires
    # ----------------------------------------------------------

    def sync_opponent_moves(self) -> bool:
        """
        Détecte le coup adversaire via les logs BGA (prioritaire)
        ou via comparaison du plateau DOM (fallback).
        """
        if not self.local_game:
            return False

        # ── Méthode 1 : logs BGA ────────────────────────────
        log_moves = read_log_moves(self.driver)
        n_total   = len(log_moves)

        # Désynchronisation importante → resync complet
        if n_total > len(self.local_game.moves) + 2:
            log(f"Désync ({n_total} logs / {len(self.local_game.moves)} local) → resync")
            self._resync_full_board()
            self._n_log_applied = n_total
            return True

        if n_total > self._n_log_applied and log_moves:
            last_name, last_col1 = log_moves[0]   # plus récent en premier

            # C'est notre coup → déjà appliqué localement
            if self.my_name and last_name.lower() == self.my_name.lower():
                self._n_log_applied = n_total
                return False

            # Coup adversaire
            col0 = last_col1 - 1
            if not (0 <= col0 < self.local_game.cols):
                return False
            if self.local_game.current_turn != self.their_color:
                log("Tour incohérent → resync")
                self._resync_full_board()
                self._n_log_applied = n_total
                return True

            ok = self.local_game.drop_in_column(col0)
            self._n_log_applied = n_total
            if ok:
                log(f"[LOG] Coup adversaire: colonne {last_col1}")
                self.last_known_board = [r[:] for r in self.local_game.board]
                return True
            else:
                log(f"Coup log invalide → resync")
                self._resync_full_board()
                return True

        # ── Méthode 2 : comparaison DOM ─────────────────────
        dom_board = read_board_from_dom(
            self.driver, self.local_game.rows, self.local_game.cols
        )
        if dom_board is None:
            return False

        if boards_equal(self.local_game.board, dom_board):
            return False

        result = find_new_move(self.local_game.board, dom_board,
                               self.local_game.rows, self.local_game.cols)
        if result is None:
            return False

        row0, col0 = result
        new_color  = dom_board[row0][col0]

        if new_color != self.their_color:
            log(f"[DOM] Changement inattendu ({row0},{col0}) color={new_color}")
            return False

        if self.local_game.current_turn != self.their_color:
            return False

        ok = self.local_game.drop_in_column(col0)
        if ok:
            log(f"[DOM] Coup adversaire: col={col0+1} row={row0+1}")
            self.last_known_board = [r[:] for r in self.local_game.board]
            return True

        return False

    def _count_log_moves(self) -> int:
        """Compte le nombre total de coups dans les logs BGA."""
        try:
            count = 0
            for el in self.driver.find_elements(By.CSS_SELECTOR, "#logs .log_replayable"):
                if "place un pion" in (el.text or "").lower():
                    count += 1
            return count
        except Exception:
            return 0

    # ----------------------------------------------------------
    # Notre coup avec l'IA
    # ----------------------------------------------------------

    def choose_ai_column(self) -> Optional[int]:
        """Utilise ai_engine pour choisir la meilleure colonne (0-based)."""
        if not self.local_game:
            return None
        try:
            col = ai_choose_column_from_game(
                self.local_game,
                db_available=True,
                robot_depth=AI_DEPTH,
                mode="strategic"
            )
            return col
        except Exception as e:
            log(f"Erreur IA: {e} → fallback centre")
            valid = self.local_game.valid_columns()
            if valid:
                center = self.local_game.cols // 2
                valid.sort(key=lambda c: abs(c - center))
                return valid[0]
            return None

    def get_clickable_element_for_col(self, col0: int):
        """Retourne l'élément cliquable BGA pour la colonne col0 (0-based)."""
        try:
            bga_col = col0 + 1
            for sel in [
                f"#board .square.possibleMove[id^='square_{bga_col}_']",
                f"#board .square[id^='square_{bga_col}_']",
            ]:
                squares = [s for s in self.driver.find_elements(By.CSS_SELECTOR, sel)
                           if s.is_displayed()]
                if squares:
                    return squares[0]
        except Exception:
            pass
        return None

    def play_our_turn(self) -> str:
        """Joue notre coup avec l'IA. Retourne 'MOVED', 'GAME_OVER' ou 'WAITING'."""
        if self.is_game_over_ui():
            self.finalize()
            return "GAME_OVER"

        if not self.local_game or self.local_game.finished:
            return "GAME_OVER"

        if self.local_game.current_turn != self.my_color:
            return "WAITING"

        if not self.is_my_turn_bga():
            return "WAITING"

        # Resync avant de jouer pour garantir un état correct
        self._resync_full_board()

        if not self.local_game or self.local_game.finished:
            return "GAME_OVER"
        if self.local_game.current_turn != self.my_color:
            return "WAITING"

        col0 = self.choose_ai_column()
        if col0 is None:
            log("IA n'a pas trouvé de coup valide.")
            return "WAITING"

        log(f"IA choisit colonne {col0+1}")

        el = self.get_clickable_element_for_col(col0)
        if el is None:
            log(f"Élément cliquable introuvable pour col={col0+1}")
            return "WAITING"

        ok = self.local_game.drop_in_column(col0)
        if not ok:
            log(f"drop_in_column refusé pour col={col0+1}")
            return "WAITING"

        last = self.local_game.moves[-1]
        log(f"Notre coup : col={last.col+1} row={last.row+1} color={last.color}")

        try:
            self.driver.execute_script("arguments[0].click();", el)
        except Exception as e:
            log(f"Échec clic: {e}")
            self.local_game.undo()
            return "WAITING"

        self.last_known_board = [row[:] for row in self.local_game.board]
        self._n_log_applied  += 1

        time.sleep(AFTER_MOVE_WAIT)
        self.save_progress()

        if self.local_game.finished:
            self.finalize()
            return "GAME_OVER"

        return "MOVED"

    # ----------------------------------------------------------
    # Helpers état BGA
    # ----------------------------------------------------------

    def is_game_over_ui(self) -> bool:
        try:
            title = self.driver.find_elements(By.ID, "pagemaintitletext")
            if title:
                txt = (title[0].text or "").lower()
                if any(kw in txt for kw in ["fin de la partie", "victoire", "match nul"]):
                    log(f"Fin détectée: {title[0].text}")
                    return True
        except Exception:
            pass
        return False

    def is_my_turn_bga(self) -> bool:
        """Vérifie si BGA nous donne la main via possibleMove."""
        try:
            body_cls = self.driver.find_element(
                By.TAG_NAME, "body").get_attribute("class") or ""
            if "current_player_is_active" not in body_cls:
                return False
            possibles = [p for p in self.driver.find_elements(
                By.CSS_SELECTOR, "#board .square.possibleMove") if p.is_displayed()]
            return len(possibles) > 0
        except Exception:
            return False

    # ----------------------------------------------------------
    # DB
    # ----------------------------------------------------------

    def save_progress(self):
        if not self.local_game or not self.current_source:
            return
        moves_list = self.local_game.moves
        if not moves_list:
            return
        moves_payload = [
            {"ply": i+1, "col": int(m.col), "row": int(m.row), "color": m.color}
            for i, m in enumerate(moves_list)
        ]
        seq = ",".join(str(m.col + 1) for m in moves_list)
        ok, msg, gid = db.upsert_game_progress(
            source_filename=self.current_source,
            seq=seq,
            rows=self.local_game.rows,
            cols=self.local_game.cols,
            starting_color=self.local_game.starting_color,
            status="FINISHED" if self.local_game.finished else "IN_PROGRESS",
            winner=self.local_game.winner,
            draw=bool(self.local_game.draw),
            moves=moves_payload,
            confiance=CONFIANCE,
        )
        if ok:
            log(f"DB save OK | gid={gid} | coups={len(moves_list)}")
        else:
            log(f"DB save SKIP | {msg}")

    def finalize(self):
        if not self.local_game or not self.current_source:
            return
        moves_payload = [
            {"ply": i+1, "col": int(m.col), "row": int(m.row), "color": m.color}
            for i, m in enumerate(self.local_game.moves)
        ]
        seq    = ",".join(str(m.col + 1) for m in self.local_game.moves)
        winner = self.local_game.winner if self.local_game.winner in (RED, YELLOW) else None
        draw   = bool(self.local_game.draw)
        ok, msg, gid = db.upsert_game_progress(
            source_filename=self.current_source,
            seq=seq,
            rows=self.local_game.rows,
            cols=self.local_game.cols,
            starting_color=self.local_game.starting_color,
            status="FINISHED",
            winner=winner,
            draw=draw,
            moves=moves_payload,
            confiance=CONFIANCE,
        )
        log(f"DB finalize {'OK' if ok else 'SKIP'} | gid={gid} | winner={winner} | draw={draw}")

    # ----------------------------------------------------------
    # Boucle principale
    # ----------------------------------------------------------

    def run_one_game(self):
        """Joue une partie complète."""
        self.start_new_local_match()
        log(f"Partie #{self.match_counter} lancée | nous={self.my_color}")
        consecutive_wait = 0

        while True:
            if not self.is_still_in_game():
                log("Sorti du jeu, tentative de retour...")
                if self.find_active_game():
                    log("Partie retrouvée, resync...")
                    self._resync_full_board()
                    consecutive_wait = 0
                    continue
                else:
                    self.finalize()
                    return

            self.clear_popups()

            if self.is_game_over_ui():
                log("Fin de partie détectée.")
                self.finalize()
                time.sleep(AFTER_GAME_WAIT)
                return

            if self.local_game and self.local_game.finished:
                self.finalize()
                time.sleep(AFTER_GAME_WAIT)
                return

            # Tour adversaire → lire son coup
            if self.local_game and self.local_game.current_turn == self.their_color:
                got_move = self.sync_opponent_moves()
                if got_move:
                    log("Coup adversaire reçu → notre tour")
                    consecutive_wait = 0
                    self.save_progress()
                else:
                    consecutive_wait += 1
                    time.sleep(POLL_SECONDS)
                continue

            # Notre tour → jouer avec l'IA
            status = self.play_our_turn()

            if status == "GAME_OVER":
                log(f"Partie #{self.match_counter} terminée.")
                time.sleep(AFTER_GAME_WAIT)
                return
            elif status == "MOVED":
                log("Coup joué, attente réponse adversaire...")
                consecutive_wait = 0
            else:
                consecutive_wait += 1
                time.sleep(POLL_SECONDS)

            # Attente trop longue → resync
            if consecutive_wait > 15:
                log("Attente trop longue → resync complet")
                self._resync_full_board()
                consecutive_wait = 0

    def run_forever(self):
        self.login()

        while True:
            banner("Nouvelle session BGA")
            try:
                # FIX 1 : reprendre une partie en cours si elle existe
                if self.find_active_game():
                    log("Reprise d'une partie active...")
                    self.match_counter += 1
                    self.my_color     = self.detect_my_color()
                    self.their_color  = YELLOW if self.my_color == RED else RED
                    self.current_source = f"bga_bot_ia_{int(time.time())}_{self.match_counter}"
                    self._n_log_applied = 0
                    self._resync_full_board()
                    self.run_one_game()
                    continue

                self.navigate_to_game()
                self.select_realtime_mode()

                if not self.start_table():
                    log("Impossible de démarrer une table.")
                    time.sleep(5)
                    continue

                self.run_one_game()

            except KeyboardInterrupt:
                raise
            except WebDriverException as e:
                log(f"Erreur WebDriver: {e}")
                if not self.is_logged_in():
                    self.reconnect()
                time.sleep(5)
            except Exception as e:
                log(f"Erreur inattendue: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(5)

    def close(self):
        try:
            self.driver.quit()
        except Exception:
            pass


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    bot = BGAIACombot()
    try:
        bot.run_forever()
    except KeyboardInterrupt:
        log("Arrêt demandé.")
    except Exception as e:
        log(f"Erreur fatale: {e}")
    finally:
        bot.close()
