from __future__ import annotations

import re
import time
import tempfile
from pathlib import Path
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


BASE = "https://boardgamearena.com"

# Mets False pour voir Chrome s’ouvrir et éviter certains crashs headless
HEADLESS = False

# Commence sans profil persistant pour vérifier que Chrome démarre
USE_PERSISTENT_PROFILE = False

PROJECT_DIR = Path(__file__).resolve().parent
CHROME_PROFILE_DIR = PROJECT_DIR / "chrome_profile_bga"
CHROME_PROFILE_DIR.mkdir(exist_ok=True)

SIZE_RE = re.compile(r"(\d{1,2})\s*[x×]\s*(\d{1,2})", re.IGNORECASE)

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
    .sort((a, b) => a[0] - b[0])
    .map(([move_id, v]) => ({
      move_id,
      col: v.col,
      player_id: v.pid
    }));

  return { count: moves.length, moves };
})();
"""


def make_driver(headless: bool = HEADLESS):
    opts = Options()

    if headless:
        # plus stable que --headless=new sur certaines configs Windows
        opts.add_argument("--headless")
        opts.add_argument("--window-size=1400,1000")
    else:
        opts.add_argument("--start-maximized")

    # important pour éviter le crash Chrome/DevToolsActivePort
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--remote-debugging-port=9222")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--disable-blink-features=AutomationControlled")

    if USE_PERSISTENT_PROFILE:
        opts.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
        opts.add_argument("--profile-directory=Default")
    else:
        # profil temporaire propre à chaque lancement
        temp_profile = tempfile.mkdtemp(prefix="bga_chrome_")
        opts.add_argument(f"--user-data-dir={temp_profile}")

    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(60)
    return driver
# ============================================================
# SIZE DETECTION
# ============================================================

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


def get_board_size_from_table_page(driver, table_id: str):
    try:
        tid = str(int(str(table_id)))
    except Exception:
        return None

    url = f"{BASE}/table?table={tid}"
    driver.get(url)

    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(1.0)

        # cas le plus fiable
        try:
            el = driver.find_element(By.ID, "gameoption_100_displayed_value")
            val = (el.text or "").strip()
            m = re.search(r"(\d{1,2})\s*[x×]\s*(\d{1,2})", val)
            if m:
                return (int(m.group(1)), int(m.group(2)))
        except Exception:
            pass

        # fallback texte brut
        page_text = driver.find_element(By.TAG_NAME, "body").text or ""
        lines_ = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        for i, ln in enumerate(lines_):
            ll = ln.lower()
            if ("taille" in ll and "plateau" in ll) or ("board" in ll and "size" in ll):
                window = " ".join(lines_[i:i + 5])
                m = re.search(r"(\d{1,2})\s*[x×]\s*(\d{1,2})", window)
                if m:
                    return (int(m.group(1)), int(m.group(2)))
    except Exception:
        pass

    return None


# ============================================================
# GAMEREVIEW EXTRACTION
# ============================================================

def extract_size_and_moves_from_gamereview(driver, table_id: str):
    url = f"{BASE}/gamereview?table={table_id}"
    driver.get(url)

    WebDriverWait(driver, 25).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
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

    # version plus tolérante
    pattern = re.compile(
        r"^(.+?)\s+place.*?colonne\s+(\d+)\s*$",
        re.MULTILINE | re.IGNORECASE
    )
    rows = pattern.findall(page_text)

    moves = []
    move_id = 1
    for player_name, col_str in rows:
        player_name = player_name.strip()
        col = int(col_str)
        pid = name_to_pid.get(player_name, "unknown")
        moves.append({
            "move_id": move_id,
            "col": col,
            "player_id": str(pid)
        })
        move_id += 1

    return size, moves


# ============================================================
# ARCHIVE / REPLAY FALLBACK
# ============================================================

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


def resolve_real_replay_url_from_table(driver, table_id: str):
    table_url = f"{BASE}/table?table={table_id}"
    driver.get(table_url)

    wait = WebDriverWait(driver, 20)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(1.0)

    try:
        a = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="/archive/replay/"]'))
        )
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
    WebDriverWait(driver, 25).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    time.sleep(2)

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
# PUBLIC API FOR serveur.py
# ============================================================

def load_bga_table(table_id: int) -> dict:
    """
    Retourne un dict compatible avec serveur.py :
    {
        "rows": 9,
        "cols": 9,
        "starting_color": "R",
        "moves": [{"col": 4}, {"col": 5}, ...]
    }

    Important:
    - BGA archive renvoie souvent des colonnes 0-based
    - gamereview texte renvoie souvent des colonnes 1-based
    Ici on normalise tout en 0-based pour ton moteur Connect4.
    """
    driver = make_driver(headless=HEADLESS)

    try:
        tid = int(table_id)

        size = get_board_size_from_table_page(driver, tid)
        if size is None:
            # fallback si taille non détectée
            size = (9, 9)

        rows_count, cols_count = size

        # 1) tentative gamereview
        _size_from_review, moves = extract_size_and_moves_from_gamereview(driver, tid)
        source = "gamereview"

        # gamereview texte => souvent colonnes 1-based
        if moves:
            normalized = []
            for m in moves:
                col0 = int(m["col"]) - 1
                if 0 <= col0 < cols_count:
                    normalized.append({"col": col0})
            moves = normalized

        # 2) fallback archive
        if not moves:
            replay_url = resolve_real_replay_url_from_table(driver, tid)
            if replay_url:
                source = "archive"
                raw_moves = extract_moves_from_replay_url(driver, replay_url)

                # archive/g_gamelogs => déjà 0-based
                normalized = []
                for m in raw_moves:
                    col0 = int(m["col"])
                    if 0 <= col0 < cols_count:
                        normalized.append({"col": col0})
                moves = normalized

        if not moves:
            raise RuntimeError(f"Aucun coup trouvé pour la table {tid}")

        return {
            "table_id": tid,
            "rows": rows_count,
            "cols": cols_count,
            "starting_color": "R",
            "source": source,
            "moves": moves,
        }

    finally:
        driver.quit()
