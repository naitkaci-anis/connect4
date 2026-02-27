

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

GAME_ID = 1186              # connectfour
FINISHED = 1                # 1 = terminées

ROWS = 9
COLS = 9
CONFIANCE = 3               # 3=BGA/humain (voir mapping confiance)

ONLY_9X9 = True
STRICT_SIZE_CHECK = True

MAX_PLAYERS = 40
MAX_TABLES_PER_PLAYER = 80
SCROLL_STEPS = 20
SLEEP_SCROLL = 0.6
PAUSE_BETWEEN_PLAYERS = 0.6
PAUSE_BETWEEN_TABLES = 1.0

BASE = "https://boardgamearena.com"

PROJECT_DIR = Path(__file__).resolve().parent
OUT_DIR = PROJECT_DIR / "scraped_moves"
OUT_DIR.mkdir(exist_ok=True)

# =============================
# TXT OUTPUT SETTINGS
# =============================
# "single"  -> un seul fichier global (recommandé)
# "per_player" -> un fichier par joueur
SAVE_MODE = "single"
OUT_TXT_GLOBAL = OUT_DIR / "all_connect4_9x9_moves.txt"


# ============================================================
# PRETTY LOGS (originaux)
# ============================================================

ICONS = {
    "login": "🔐",
    "rank": "🏁",
    "player": "🧑‍💻",
    "table": "🧩",
    "find": "🔎",
    "size": "📐",
    "src": "🧭",
    "ok": "✅",
    "skip": "⏭️",
    "fail": "🚫",
    "txt": "📝",
    "db": "💾",
    "wait": "⏱️",
    "done": "🎉",
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
    table_id: str,
    size: tuple | None,
    moves: list,
    source: str,
    outfile: Path
):
    """
    Ecrit une partie dans un .txt
    - moves: [{"move_id":1,"col":5,"player_id":"123"}, ...]
    - source: "gamereview" ou "archive"
    """
    # Séquence simple: colonnes concaténées (ex: "5567...")
    seq = "".join(str(m.get("col", "")) for m in moves if m.get("col") is not None)

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

def get_board_size_from_table_page(driver, table_id: str):
    try:
        tid = str(int(str(table_id)))
    except Exception:
        return None

    url = f"{BASE}/table?table={tid}"
    driver.get(url)

    try:
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.ID, "gameoption_100_displayed_value"))
        )
        time.sleep(0.6)
        el = driver.find_element(By.ID, "gameoption_100_displayed_value")
        val = (el.text or "").strip()
        m = re.search(r"(\d{1,2})\s*[x×]\s*(\d{1,2})", val)
        if m:
            r = int(m.group(1)); c = int(m.group(2))
            return (r, c)
    except Exception:
        try:
            page_text = driver.find_element(By.TAG_NAME, "body").text or ""
            lines_ = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
            for i, ln in enumerate(lines_):
                ll = ln.lower()
                if ("taille" in ll and "plateau" in ll) or ("board" in ll and "size" in ll):
                    window = " ".join(lines_[i:i+5])
                    m = re.search(r"(\d{1,2})\s*[x×]\s*(\d{1,2})", window)
                    if m:
                        r = int(m.group(1)); c = int(m.group(2))
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

    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(60)
    return driver


# ============================================================
# LOGIN MANUEL + FIX DOMAINE
# ============================================================

def login_bga_manual(driver):
    global BASE
    banner(f"{ICONS['login']} Connexion BGA (manuel)")

    line("Ouverture page compte…")
    driver.get(f"{BASE}/account")

    line("Connecte-toi MANUELLEMENT dans Chrome.")
    input("✅ Connexion détectée, appuie sur ENTRÉE pour continuer...")

    line(f"URL actuelle : {driver.current_url}")

    u = urlparse(driver.current_url)
    BASE = f"{u.scheme}://{u.netloc}"
    line(f"BASE fixé à : {BASE}")


# ============================================================
# 0) Joueurs depuis classement Connect4
# ============================================================

def collect_player_ids_from_ranking(driver, max_players: int, scroll_steps: int):
    banner(f"{ICONS['rank']} Récupération des joueurs (classement)")

    url = f"{BASE}/gamepanel?game=connectfour"
    line(f"Ouverture: {url}")
    driver.get(url)

    WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(2)

    line(f"Scroll x{scroll_steps} pour charger la liste…")
    for _ in range(scroll_steps):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SLEEP_SCROLL)

    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(1)

    anchors = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/player?id="]')
    ids = []
    for a in anchors:
        href = a.get_attribute("href") or ""
        m = re.search(r"/player\?id=(\d+)", href)
        if m:
            ids.append(m.group(1))

    uniq = list(dict.fromkeys(ids))[:max_players]
    line(f"{ICONS['ok']} player_ids trouvés = {len(uniq)} (max={max_players})")
    if uniq:
        line(f"sample: {uniq[:10]}")
    return uniq


# ============================================================
# 1) TABLE IDS depuis gamestats
# ============================================================

def get_connect4_table_ids(driver, player_id: str, game_id: int, finished: int, limit: int):
    url = f"{BASE}/gamestats?player={player_id}&game_id={game_id}&finished={finished}"
    driver.get(url)
    time.sleep(2)

    for _ in range(10):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.7)

    html = driver.page_source or ""
    raw = re.findall(r"(?:/table\?table=|table\?table=|[?&]table=)(\d+)", html)

    table_ids = []
    for t in raw:
        try:
            n = int(t)
            if n > 0:
                table_ids.append(str(n))
        except ValueError:
            pass

    seen = set()
    table_ids = [x for x in table_ids if not (x in seen or seen.add(x))]
    table_ids = table_ids[:limit]

    line(f"{ICONS['ok']} tables trouvées = {len(table_ids)} (limit={limit})")
    return table_ids


# ============================================================
# 2) Detect board size anchored (gamereview text)
# ============================================================

SIZE_RE = re.compile(r"(\d{1,2})\s*[x×]\s*(\d{1,2})", re.IGNORECASE)

def detect_board_size_anchored(page_text: str):
    if not page_text:
        return None

    lower = page_text.lower()
    if "9x9" in lower or "9×9" in lower:
        return (9, 9)

    for line_ in page_text.splitlines():
        l = line_.strip()
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

    return None


# ============================================================
# 3) Extraction coups via /gamereview?table=...
# ============================================================

def extract_size_and_moves_from_gamereview(driver, table_id: str):
    url = f"{BASE}/gamereview?table={table_id}"
    driver.get(url)

    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(1.2)

    body_el = driver.find_element(By.TAG_NAME, "body")
    page_text = body_el.text or ""

    size = detect_board_size_anchored(page_text)

    name_to_pid = {}
    try:
        links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/player?id="]')
        for a in links:
            href = a.get_attribute("href") or ""
            m = re.search(r"/player\?id=(\d+)", href)
            if not m:
                continue
            pid = m.group(1)
            name = (a.text or "").strip()
            if name and name not in name_to_pid:
                name_to_pid[name] = pid
    except Exception:
        pass

    pattern = re.compile(r"^(.+?)\s+place un pion dans la colonne\s+(\d+)\s*$", re.MULTILINE)
    rows = pattern.findall(page_text)

    moves = []
    move_id = 1
    for player_name, col_str in rows:
        player_name = player_name.strip()
        col = int(col_str)
        pid = name_to_pid.get(player_name, "unknown")
        moves.append({"move_id": move_id, "col": col, "player_id": str(pid)})
        move_id += 1

    return size, moves


# ============================================================
# 4) Fallback replay archive via g_gamelogs
# ============================================================

EXTRACT_JS = r"""
return (function () {
  const byMove = new Map();
  for (const pkt of (window.g_gamelogs || [])) {
    const mid = Number(pkt && pkt.move_id);
    if (!Number.isFinite(mid)) continue;

    const data = (pkt.data || []);
    const disc = data.find(d => d && d.type === "playDisc");
    if (!disc || !disc.args) continue;

    const col = Number(disc.args.x);
    const pid = String(disc.args.player_id);
    if (!Number.isFinite(col)) continue;

    byMove.set(mid, { col, pid });
  }

  const moves = [...byMove.entries()]
    .sort((a,b)=>a[0]-b[0])
    .map(([move_id, v]) => ({ move_id, col: v.col, player_id: v.pid }));

  return { count: moves.length, moves };
})();
"""

def wait_gamelogs(driver, max_wait=30):
    end = time.time() + max_wait
    while time.time() < end:
        n = driver.execute_script("return (window.g_gamelogs && window.g_gamelogs.length) || 0;")
        if int(n) > 0:
            return True
        time.sleep(0.5)
    return False

def resolve_real_replay_url_from_table(driver, table_id: str):
    table_url = f"{BASE}/table?table={table_id}"
    driver.get(table_url)

    wait = WebDriverWait(driver, 20)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    try:
        a = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="/archive/replay/"]')))
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

    return None

def extract_moves_from_replay_url(driver, replay_url: str):
    driver.get(replay_url)
    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(2)

    ok = wait_gamelogs(driver, max_wait=30)
    if not ok:
        return []

    for _ in range(1, 6):
        payload = driver.execute_script(EXTRACT_JS)
        if payload and payload.get("count", 0) > 0:
            return payload["moves"]
        time.sleep(1.0)

    return []


# ============================================================
# 5) Import DB (optionnel)
# ============================================================

def import_into_db(moves, table_id: str, player_id: str):
    import bga_import


    source = f"bga_table_{table_id}_p{player_id}"

    id_partie = bga_import.import_bga_moves(
        moves,
        rows=ROWS,
        cols=COLS,
        confiance=CONFIANCE,
        source_filename=source,
        starting_color="R",
    )

    return id_partie


# ============================================================
# MAIN
# ============================================================

def main():
    driver = make_driver(headless=False)

    try:
        login_bga_manual(driver)

        player_ids = collect_player_ids_from_ranking(
            driver,
            max_players=MAX_PLAYERS,
            scroll_steps=SCROLL_STEPS
        )

        if not player_ids:
            banner(f"{ICONS['fail']} Aucun player_id trouvé")
            return

        banner("🚀 Lancement du scrape")

        total_seen = 0
        total_imported = 0
        total_saved_txt = 0
        total_skipped = 0

        for idx, player_id in enumerate(player_ids, start=1):
            player_header(idx, len(player_ids), player_id)

            # Choix fichier txt
            if SAVE_MODE == "per_player":
                out_txt = OUT_DIR / f"player_{player_id}_connect4_9x9.txt"
            else:
                out_txt = OUT_TXT_GLOBAL

            table_ids = get_connect4_table_ids(driver, player_id, GAME_ID, FINISHED, MAX_TABLES_PER_PLAYER)
            if not table_ids:
                line(f"{ICONS['skip']} aucune table pour ce joueur.")
                continue

            for tid in table_ids:
                total_seen += 1
                table_line(tid, f"{ICONS['find']} analyse…")

                # 1) Open table page: reliable size
                size = get_board_size_from_table_page(driver, tid)
                if size:
                    table_line(tid, f"{ICONS['size']} taille détectée: {size[0]}x{size[1]}")
                else:
                    table_line(tid, f"{ICONS['size']} taille inconnue")

                # 2) Filter 9x9
                if ONLY_9X9:
                    if size is None:
                        if STRICT_SIZE_CHECK:
                            table_line(tid, f"{ICONS['skip']} size inconnue (strict) → skip")
                            total_skipped += 1
                            time.sleep(PAUSE_BETWEEN_TABLES)
                            continue
                    else:
                        r, c = size
                        if (r, c) != (9, 9):
                            table_line(tid, f"{ICONS['skip']} {r}x{c} ≠ 9x9 → skip")
                            total_skipped += 1
                            time.sleep(PAUSE_BETWEEN_TABLES)
                            continue

                # 3) Extract moves from gamereview
                _size_from_gamereview, moves = extract_size_and_moves_from_gamereview(driver, tid)
                source = "gamereview"
                if moves:
                    table_line(tid, f"{ICONS['ok']} {len(moves)} coups via {ICONS['src']} gamereview")

                # fallback to archive replay
                if not moves:
                    replay_url = resolve_real_replay_url_from_table(driver, tid)
                    if replay_url:
                        table_line(tid, f"{ICONS['src']} fallback archive…")
                        moves = extract_moves_from_replay_url(driver, replay_url)
                        source = "archive"
                        if moves:
                            table_line(tid, f"{ICONS['ok']} {len(moves)} coups via {ICONS['src']} archive")

                if not moves:
                    table_line(tid, f"{ICONS['fail']} replay vide… {ICONS['skip']} on passe")
                    total_skipped += 1
                    time.sleep(PAUSE_BETWEEN_TABLES)
                    continue

                # TXT save
                append_game_to_txt(
                    player_id=player_id,
                    table_id=tid,
                    size=size,
                    moves=moves,
                    source=source,
                    outfile=out_txt
                )
                total_saved_txt += 1
                table_line(tid, f"{ICONS['txt']} TXT ajouté → {out_txt.name}")

                # Import DB
                try:
                    id_partie = import_into_db(moves, table_id=tid, player_id=player_id)
                    total_imported += 1
                    table_line(tid, f"{ICONS['db']} DB OK (id_partie={id_partie})")
                except Exception as e:
                    table_line(tid, f"{ICONS['fail']} DB FAILED: {e}")

                time.sleep(PAUSE_BETWEEN_TABLES)

            time.sleep(PAUSE_BETWEEN_PLAYERS)

        banner(f"{ICONS['done']} Terminé")
        line(f"Tables vues      : {total_seen}")
        line(f"TXT sauvegardées : {total_saved_txt}")
        line(f"Importées en DB  : {total_imported}")
        line(f"Skips            : {total_skipped}")
        line(f"Dossier TXT      : {OUT_DIR}")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
