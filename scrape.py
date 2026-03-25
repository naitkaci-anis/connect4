import json
import time
import re
from pathlib import Path
from urllib.parse import urlparse, urljoin

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ============================================================
# CONFIG
# ============================================================

GAME_ID  = 1186          # connectfour
FINISHED = 1             # 1 = terminées

ROWS      = 9
COLS      = 9
CONFIANCE = 3            # 3=BGA/humain

ONLY_9X9          = True
STRICT_SIZE_CHECK = False   # False = on tente quand même si taille inconnue

MAX_PLAYERS           = 300   # ↑ augmenté (avant : 40)
MAX_TABLES_PER_PLAYER = 150   # ↑ augmenté (avant : 80)
SCROLL_STEPS          = 40    # ↑ plus de scroll pour charger plus de joueurs
SLEEP_SCROLL          = 0.4
PAUSE_BETWEEN_PLAYERS = 0.3   # ↓ réduit
PAUSE_BETWEEN_TABLES  = 0.6   # ↓ réduit

BASE = "https://boardgamearena.com"

PROJECT_DIR    = Path(__file__).resolve().parent
OUT_DIR        = PROJECT_DIR / "scraped_moves"
OUT_DIR.mkdir(exist_ok=True)

SAVE_MODE      = "single"
OUT_TXT_GLOBAL = OUT_DIR / "all_connect4_9x9_moves.txt"


# ============================================================
# CACHE — charge les table_ids et player_ids déjà scrapés
# ============================================================

def load_cache_from_txt(txt_path: Path) -> tuple[set, set]:
    """
    Lit le fichier TXT existant et retourne :
      - seen_table_ids  : set des table_id déjà scrapées
      - seen_player_ids : set des player_id déjà vus (pour les prioriser
                          comme source de nouveaux adversaires)
    """
    seen_tables  = set()
    seen_players = set()

    if not txt_path.exists():
        return seen_tables, seen_players

    with open(txt_path, encoding="utf-8") as f:
        for raw_line in f:
            line_ = raw_line.strip()
            if line_.startswith("table_id:"):
                tid = line_.split(":", 1)[1].strip()
                if tid:
                    seen_tables.add(tid)
            elif line_.startswith("player_id:"):
                pid = line_.split(":", 1)[1].strip()
                if pid:
                    seen_players.add(pid)

    return seen_tables, seen_players


def extract_opponent_ids_from_txt(txt_path: Path) -> set:
    """
    Extrait TOUS les player_id présents dans les lignes de coups
    (pid=XXXXXXXX) — ce sont les adversaires des joueurs déjà connus.
    C'est une mine d'or de nouveaux joueurs à scraper.
    """
    opponents = set()
    if not txt_path.exists():
        return opponents

    pattern = re.compile(r'pid=(\d{6,})')
    with open(txt_path, encoding="utf-8") as f:
        for raw_line in f:
            for m in pattern.finditer(raw_line):
                opponents.add(m.group(1))

    return opponents


# ============================================================
# PRETTY LOGS
# ============================================================

ICONS = {
    "login":  "🔐",
    "rank":   "🏁",
    "player": "🧑‍💻",
    "table":  "🧩",
    "find":   "🔎",
    "size":   "📐",
    "src":    "🧭",
    "ok":     "✅",
    "skip":   "⏭️",
    "fail":   "🚫",
    "txt":    "📝",
    "db":     "💾",
    "wait":   "⏱️",
    "done":   "🎉",
    "cache":  "💾",
}


def banner(title: str):
    print("\n" + "═" * 72)
    print(f"  {title}")
    print("═" * 72)


def section(title: str):
    print("\n" + "─" * 72)
    print(f"  {title}")
    print("─" * 72)


def line(msg: str):
    print(f"  • {msg}")


def table_line(tid: str, msg: str):
    print(f"    {ICONS['table']} {tid}  →  {msg}")


def player_header(i: int, n: int, player_id: str):
    section(f"{ICONS['player']} Joueur {i}/{n}  |  id={player_id}")


# ============================================================
# TXT utils
# ============================================================

def sanitize_filename(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", (s or "").strip()).strip("_")


def append_game_to_txt(
    player_id: str,
    table_id:  str,
    size,
    moves:     list,
    source:    str,
    outfile:   Path,
):
    seq      = "".join(str(m.get("col", "")) for m in moves if m.get("col") is not None)
    size_str = "unknown" if size is None else f"{size[0]}x{size[1]}"

    lines = []
    lines.append("=" * 60)
    lines.append(f"player_id: {player_id}")
    lines.append(f"table_id:  {table_id}")
    lines.append(f"size:      {size_str}")
    lines.append(f"source:    {source}")
    lines.append(f"moves_count: {len(moves)}")
    lines.append(f"sequence:  {seq}")
    lines.append("-" * 60)
    for m in moves:
        lines.append(f"{m.get('move_id')} | col={m.get('col')} | pid={m.get('player_id')}")
    lines.append("")

    with open(outfile, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ============================================================
# UTIL: BOARD SIZE via /table?table=...
# ============================================================

SIZE_RE = re.compile(r"(\d{1,2})\s*[x×]\s*(\d{1,2})", re.IGNORECASE)


def get_board_size_from_table_page(driver, table_id: str):
    try:
        tid = str(int(str(table_id)))
    except Exception:
        return None

    url = f"{BASE}/table?table={tid}"
    driver.get(url)

    try:
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(0.8)

        try:
            el  = driver.find_element(By.ID, "gameoption_100_displayed_value")
            val = (el.text or "").strip()
            m   = SIZE_RE.search(val)
            if m:
                return (int(m.group(1)), int(m.group(2)))
        except Exception:
            pass

        page_text = driver.find_element(By.TAG_NAME, "body").text or ""

        if "9x9" in page_text.lower() or "9×9" in page_text.lower():
            return (9, 9)

        lines_ = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        for i, ln in enumerate(lines_):
            ll = ln.lower()
            if ("taille" in ll and "plateau" in ll) or ("board" in ll and "size" in ll):
                window = " ".join(lines_[i:i+6])
                m = SIZE_RE.search(window)
                if m:
                    return (int(m.group(1)), int(m.group(2)))

        m = SIZE_RE.search(page_text)
        if m:
            r, c = int(m.group(1)), int(m.group(2))
            if 4 <= r <= 20 and 4 <= c <= 20:
                return (r, c)

    except Exception:
        pass

    return None


# ============================================================
# DRIVER
# ============================================================

def make_driver(headless: bool = False):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1400,900")
    else:
        opts.add_argument("--start-maximized")

    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(60)
    return driver


# ============================================================
# LOGIN MANUEL
# ============================================================

def login_bga_manual(driver):
    global BASE
    banner(f"{ICONS['login']} Connexion BGA (manuel)")

    line("Ouverture page compte…")
    driver.get(f"{BASE}/account")

    line("Connecte-toi MANUELLEMENT dans Chrome.")
    input("✅ Quand tu es connecté, appuie sur ENTRÉE pour continuer...")

    line(f"URL actuelle : {driver.current_url}")

    u    = urlparse(driver.current_url)
    BASE = f"{u.scheme}://{u.netloc}"
    line(f"BASE fixé à : {BASE}")


# ============================================================
# 0) Joueurs — collecte maximale
# ============================================================

def collect_player_ids_from_ranking(driver, max_players: int, scroll_steps: int) -> list:
    """
    Scrape le classement connectfour + explore les profils des joueurs
    trouvés pour récupérer leurs adversaires → beaucoup plus de joueurs.
    """
    banner(f"{ICONS['rank']} Récupération des joueurs (classement)")

    ids_found = []
    seen      = set()

    # ── Étape 1 : gamepanel principal ──────────────────────────────────
    for game_name in ["connectfour", "connect4"]:
        url = f"{BASE}/gamepanel?game={game_name}"
        line(f"Ouverture: {url}")
        driver.get(url)

        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(1.5)

        line(f"Scroll x{scroll_steps} pour charger la liste…")
        for _ in range(scroll_steps):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(SLEEP_SCROLL)

        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.5)

        anchors = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/player?id="]')
        for a in anchors:
            href = a.get_attribute("href") or ""
            m    = re.search(r"/player\?id=(\d+)", href)
            if m:
                pid = m.group(1)
                if pid not in seen:
                    seen.add(pid)
                    ids_found.append(pid)

        line(f"{ICONS['ok']} {game_name} → {len(ids_found)} joueurs")
        if ids_found:
            break   # on a trouvé, inutile d'essayer l'autre nom

    # ── Étape 2 : top players via API halloffame ────────────────────────
    for game_id in [1186, 1014]:
        try:
            url = f"{BASE}/halloffame/halloffame/getRanking.html?game={game_id}&season=0"
            driver.get(url)
            time.sleep(1)
            body = driver.find_element(By.TAG_NAME, "body").text or ""
            data = json.loads(body)
            ranking = (
                data.get("data", {}).get("ranking")
                or data.get("ranking")
                or []
            )
            for p in ranking:
                pid = str(p.get("id") or "")
                if pid and len(pid) >= 6 and pid not in seen:
                    seen.add(pid)
                    ids_found.append(pid)
            if ranking:
                line(f"{ICONS['ok']} halloffame game_id={game_id} → {len(ranking)} joueurs ajoutés")
                break
        except Exception:
            pass

    # ── Étape 3 : joueurs depuis le cache TXT (adversaires connus) ─────
    opponents = extract_opponent_ids_from_txt(OUT_TXT_GLOBAL)
    before    = len(ids_found)
    for pid in opponents:
        if len(pid) >= 6 and pid not in seen:
            seen.add(pid)
            ids_found.append(pid)
    line(f"{ICONS['cache']} cache TXT → {len(ids_found) - before} adversaires ajoutés")

    # ── Déduplique et limite ────────────────────────────────────────────
    final = list(dict.fromkeys(ids_found))[:max_players]
    line(f"{ICONS['ok']} Total player_ids = {len(final)} (max={max_players})")
    if final:
        line(f"sample: {final[:8]}")

    return final


# ============================================================
# 1) TABLE IDS depuis gamestats
# ============================================================

def get_connect4_table_ids(
    driver,
    player_id: str,
    game_id:   int,
    finished:  int,
    limit:     int,
    skip_tables: set,   # ← tables déjà scrapées à ignorer
) -> list:

    url = f"{BASE}/gamestats?player={player_id}&game_id={game_id}&finished={finished}"
    driver.get(url)

    WebDriverWait(driver, 25).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    time.sleep(1.5)

    for _ in range(12):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.5)

    html = driver.page_source or ""

    raw = []
    raw += re.findall(r"/table\?table=(\d+)", html)
    raw += re.findall(r"[?&]table=(\d+)", html)
    raw += re.findall(r'"table_id"\s*:\s*(\d+)', html)

    table_ids = []
    seen_local = set()
    for t in raw:
        try:
            n = int(str(t))
            s = str(n)
            if n > 0 and s not in seen_local:
                seen_local.add(s)
                table_ids.append(s)
        except Exception:
            pass

    # Sépare les nouvelles des déjà scrapées
    new_tables  = [t for t in table_ids if t not in skip_tables]
    skip_count  = len(table_ids) - len(new_tables)

    line(
        f"{ICONS['ok']} tables trouvées = {len(table_ids)} "
        f"| {ICONS['cache']} déjà scrapées = {skip_count} "
        f"| nouvelles = {len(new_tables[:limit])}"
    )

    return new_tables[:limit]


# ============================================================
# 2) Detect board size
# ============================================================

def detect_board_size_anchored(page_text: str):
    if not page_text:
        return None

    lower = page_text.lower()

    if "9x9" in lower or "9×9" in lower:
        return (9, 9)

    for line_ in page_text.splitlines():
        l  = line_.strip()
        if not l:
            continue
        ll = l.lower()

        anchored = (
            ("board" in ll and "size" in ll)
            or ("taille" in ll and "plateau" in ll)
            or ("grid" in ll and "size" in ll)
        )
        if not anchored:
            continue

        m = SIZE_RE.search(l)
        if m:
            r = int(m.group(1))
            c = int(m.group(2))
            if 4 <= r <= 20 and 4 <= c <= 20:
                return (r, c)

    m = SIZE_RE.search(page_text)
    if m:
        r = int(m.group(1))
        c = int(m.group(2))
        if 4 <= r <= 20 and 4 <= c <= 20:
            return (r, c)

    return None


# ============================================================
# 3) Extraction coups via JS gamelogs
# ============================================================

EXTRACT_JS = r"""
return (function () {
  function normalizeCol(x) {
    var n = Number(x);
    if (!Number.isFinite(n)) return null;
    if (n >= 0) return n + 1;   // BGA 0-based → 1-based
    return null;
  }

  const byMove = new Map();

  const packets = window.g_gamelogs || [];
  for (const pkt of packets) {
    const mid = Number(pkt && pkt.move_id);
    if (!Number.isFinite(mid)) continue;

    const data = pkt && pkt.data ? pkt.data : [];
    if (!Array.isArray(data)) continue;

    for (const d of data) {
      if (!d || !d.type || !d.args) continue;

      if (d.type === "playDisc") {
        const col = normalizeCol(d.args.x);
        const pid = String(d.args.player_id || "unknown");
        if (col !== null) {
          byMove.set(mid, { move_id: mid, col: col, player_id: pid });
        }
      }

      if ((d.type === "playToken" || d.type === "placeToken" || d.type === "dropDisc") && d.args) {
        const col = normalizeCol(d.args.x);
        const pid = String(d.args.player_id || "unknown");
        if (col !== null) {
          byMove.set(mid, { move_id: mid, col: col, player_id: pid });
        }
      }
    }
  }

  const moves = [...byMove.values()]
    .sort((a, b) => a.move_id - b.move_id)
    .map((m, i) => ({
      move_id: i + 1,
      col: m.col,
      player_id: m.player_id
    }));

  return { count: moves.length, moves };
})();
"""


def wait_gamelogs(driver, max_wait=30):
    end = time.time() + max_wait
    while time.time() < end:
        try:
            n = driver.execute_script(
                "return (window.g_gamelogs && window.g_gamelogs.length) || 0;"
            )
            if int(n) > 0:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


# ============================================================
# 4) Extraction coups via texte gamereview
# ============================================================

def extract_moves_from_review_text(driver):
    body_el   = driver.find_element(By.TAG_NAME, "body")
    page_text = body_el.text or ""

    name_to_pid = {}
    try:
        links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/player?id="]')
        for a in links:
            href = a.get_attribute("href") or ""
            m    = re.search(r"/player\?id=(\d+)", href)
            if not m:
                continue
            pid  = m.group(1)
            name = (a.text or "").strip()
            if name and name not in name_to_pid:
                name_to_pid[name] = pid
    except Exception:
        pass

    patterns = [
        re.compile(r"^(.+?)\s+place un pion dans la colonne\s+(\d+)\s*$", re.MULTILINE),
        re.compile(r"^(.+?)\s+places a disc in column\s+(\d+)\s*$",       re.MULTILINE),
        re.compile(r"^(.+?)\s+plays in column\s+(\d+)\s*$",               re.MULTILINE),
    ]

    rows = []
    for pattern in patterns:
        rows = pattern.findall(page_text)
        if rows:
            break

    moves   = []
    move_id = 1
    for player_name, col_str in rows:
        player_name = player_name.strip()
        col = int(col_str)
        pid = name_to_pid.get(player_name, "unknown")
        moves.append({"move_id": move_id, "col": col, "player_id": str(pid)})
        move_id += 1

    return moves, page_text


# ============================================================
# 5) Extraction principale depuis gamereview
# ============================================================

def extract_size_and_moves_from_gamereview(driver, table_id: str):
    url = f"{BASE}/gamereview?table={table_id}"
    driver.get(url)

    WebDriverWait(driver, 25).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    time.sleep(1.5)

    body_el   = driver.find_element(By.TAG_NAME, "body")
    page_text = body_el.text or ""

    size  = detect_board_size_anchored(page_text)
    moves = []

    try:
        ok = wait_gamelogs(driver, max_wait=8)
        if ok:
            payload = driver.execute_script(EXTRACT_JS)
            if payload and payload.get("count", 0) > 0:
                moves = payload["moves"]
    except Exception:
        pass

    if not moves:
        moves, _ = extract_moves_from_review_text(driver)

    return size, moves


# ============================================================
# 6) Fallback replay archive
# ============================================================

def resolve_real_replay_url_from_table(driver, table_id: str):
    table_url = f"{BASE}/table?table={table_id}"
    driver.get(table_url)

    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    time.sleep(0.8)

    for sel in ['a[href*="/archive/replay/"]', 'a[href*="archive/replay"]']:
        try:
            a    = driver.find_element(By.CSS_SELECTOR, sel)
            href = a.get_attribute("href")
            if href:
                return href
        except Exception:
            pass

    html = driver.page_source or ""

    m = re.search(r'(/archive/replay/[^"\']+)', html)
    if m:
        rel = m.group(1)
        return rel if rel.startswith("http") else urljoin(BASE, rel)

    m = re.search(r'"(https?://[^"]+/archive/replay/[^"]+)"', html)
    if m:
        return m.group(1)

    return None


def extract_moves_from_replay_url(driver, replay_url: str):
    driver.get(replay_url)
    WebDriverWait(driver, 25).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    time.sleep(1.5)

    ok = wait_gamelogs(driver, max_wait=30)
    if not ok:
        return []

    for _ in range(5):
        try:
            payload = driver.execute_script(EXTRACT_JS)
            if payload and payload.get("count", 0) > 0:
                return payload["moves"]
        except Exception:
            pass
        time.sleep(1.0)

    return []


# ============================================================
# 7) DB HELPERS
# ============================================================

def get_bga_source(table_id: str) -> str:
    return f"bga_table_{table_id}"


def game_already_in_db_by_source(table_id: str) -> bool:
    try:
        import db
    except Exception:
        return False
    try:
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM games WHERE source_filename = %s LIMIT 1",
                (get_bga_source(table_id),),
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def import_into_db(moves, table_id: str):
    import bga_import
    return bga_import.import_bga_moves(
        moves,
        rows=ROWS,
        cols=COLS,
        confiance=CONFIANCE,
        source_filename=get_bga_source(table_id),
        starting_color="R",
    )


# ============================================================
# MAIN
# ============================================================

def main():
    # ── Chargement du cache TXT ────────────────────────────────────────
    banner(f"{ICONS['cache']} Chargement du cache")
    seen_tables_cache, seen_players_cache = load_cache_from_txt(OUT_TXT_GLOBAL)
    line(f"Tables déjà scrapées (TXT)  : {len(seen_tables_cache)}")
    line(f"Joueurs déjà vus   (TXT)    : {len(seen_players_cache)}")

    driver = make_driver(headless=False)

    try:
        login_bga_manual(driver)

        player_ids = collect_player_ids_from_ranking(
            driver,
            max_players=MAX_PLAYERS,
            scroll_steps=SCROLL_STEPS,
        )

        if not player_ids:
            banner(f"{ICONS['fail']} Aucun player_id trouvé")
            return

        banner("🚀 Lancement du scrape")

        total_seen         = 0
        total_imported     = 0
        total_saved_txt    = 0
        total_skipped      = 0
        total_cache_skip   = 0   # ← tables skippées grâce au cache TXT
        total_already_in_db = 0
        total_seen_in_run  = 0

        # Tables vues dans CE run (évite de retraiter en cas de joueurs communs)
        seen_table_ids_in_run = set()

        # Fusionne : cache TXT + run actuel pour le skip
        all_skip = seen_tables_cache | seen_table_ids_in_run

        for idx, player_id in enumerate(player_ids, start=1):
            player_header(idx, len(player_ids), player_id)

            out_txt = OUT_TXT_GLOBAL if SAVE_MODE == "single" \
                else OUT_DIR / f"player_{player_id}_connect4_9x9.txt"

            table_ids = get_connect4_table_ids(
                driver,
                player_id,
                GAME_ID,
                FINISHED,
                MAX_TABLES_PER_PLAYER,
                skip_tables=all_skip,   # ← passe le cache complet
            )

            if not table_ids:
                line(f"{ICONS['skip']} aucune nouvelle table pour ce joueur.")
                time.sleep(PAUSE_BETWEEN_PLAYERS)
                continue

            for tid in table_ids:
                total_seen += 1

                # Double vérification (table_ids est déjà filtré, mais au cas où)
                if tid in seen_table_ids_in_run:
                    table_line(tid, f"{ICONS['skip']} déjà vue dans ce run")
                    total_skipped += 1
                    total_seen_in_run += 1
                    continue

                if tid in seen_tables_cache:
                    table_line(tid, f"{ICONS['cache']} déjà dans le cache TXT → skip")
                    total_skipped  += 1
                    total_cache_skip += 1
                    continue

                seen_table_ids_in_run.add(tid)
                all_skip.add(tid)   # mise à jour dynamique du skip

                if game_already_in_db_by_source(tid):
                    table_line(tid, f"{ICONS['skip']} déjà en DB")
                    total_skipped      += 1
                    total_already_in_db += 1
                    time.sleep(PAUSE_BETWEEN_TABLES)
                    continue

                table_line(tid, f"{ICONS['find']} analyse…")

                # Détection taille
                size = get_board_size_from_table_page(driver, tid)
                if size:
                    table_line(tid, f"{ICONS['size']} taille: {size[0]}x{size[1]}")
                else:
                    table_line(tid, f"{ICONS['size']} taille inconnue")

                if ONLY_9X9 and size is not None and size != (9, 9):
                    table_line(tid, f"{ICONS['skip']} {size[0]}x{size[1]} ≠ 9x9")
                    total_skipped += 1
                    time.sleep(PAUSE_BETWEEN_TABLES)
                    continue
                # Si STRICT_SIZE_CHECK=False et taille inconnue → on tente quand même

                # Extraction coups
                review_size, moves = extract_size_and_moves_from_gamereview(driver, tid)
                source = "gamereview"

                if review_size and not size:
                    size = review_size

                if moves:
                    table_line(tid, f"{ICONS['ok']} {len(moves)} coups via gamereview")

                if not moves:
                    replay_url = resolve_real_replay_url_from_table(driver, tid)
                    if replay_url:
                        table_line(tid, f"{ICONS['src']} fallback archive…")
                        moves  = extract_moves_from_replay_url(driver, replay_url)
                        source = "archive"
                        if moves:
                            table_line(tid, f"{ICONS['ok']} {len(moves)} coups via archive")

                if not moves:
                    table_line(tid, f"{ICONS['fail']} replay vide → skip")
                    total_skipped += 1
                    time.sleep(PAUSE_BETWEEN_TABLES)
                    continue

                if ONLY_9X9 and size and size != (9, 9):
                    table_line(tid, f"{ICONS['skip']} taille finale {size[0]}x{size[1]} ≠ 9x9")
                    total_skipped += 1
                    time.sleep(PAUSE_BETWEEN_TABLES)
                    continue

                # Sauvegarde TXT
                append_game_to_txt(
                    player_id=player_id,
                    table_id=tid,
                    size=size,
                    moves=moves,
                    source=source,
                    outfile=out_txt,
                )
                # Ajoute immédiatement au cache en mémoire
                seen_tables_cache.add(tid)
                total_saved_txt += 1
                table_line(tid, f"{ICONS['txt']} TXT ajouté")

                # Import DB
                try:
                    id_partie = import_into_db(moves, table_id=tid)
                    total_imported += 1
                    table_line(tid, f"{ICONS['db']} DB OK (id={id_partie})")
                except Exception as e:
                    msg = str(e)
                    if "Déjà existante" in msg or "identique/symétrique" in msg:
                        total_skipped += 1
                        table_line(tid, f"{ICONS['skip']} doublon DB → {msg}")
                    else:
                        table_line(tid, f"{ICONS['fail']} DB FAILED: {e}")

                time.sleep(PAUSE_BETWEEN_TABLES)

            time.sleep(PAUSE_BETWEEN_PLAYERS)

        banner(f"{ICONS['done']} Terminé")
        line(f"Tables vues            : {total_seen}")
        line(f"TXT sauvegardées       : {total_saved_txt}")
        line(f"Importées en DB        : {total_imported}")
        line(f"Skippées (cache TXT)   : {total_cache_skip}")
        line(f"Déjà en DB             : {total_already_in_db}")
        line(f"Déjà vues dans run     : {total_seen_in_run}")
        line(f"Skips total            : {total_skipped}")
        line(f"Dossier TXT            : {OUT_DIR}")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
