async function api(path, method = "GET", body = null) {
    const opts = { method, headers: {} };
    if (body) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "API error");
    return data;
}

const boardEl = document.getElementById("board");
const colnumsEl = document.getElementById("colnums");

const modeEl = document.getElementById("mode");
const robotEl = document.getElementById("robot");
const depthEl = document.getElementById("depth");

const btnNew = document.getElementById("btnNew");
const btnPause = document.getElementById("btnPause");
const btnPrev = document.getElementById("btnPrev");
const btnNext = document.getElementById("btnNext");
// btnSave/btnLoad/btnLoadDb/btnSettings -> on les branche après
const btnSave = document.getElementById("btnSave");
const btnLoad = document.getElementById("btnLoad");
const btnLoadDb = document.getElementById("btnLoadDb");
const btnSettings = document.getElementById("btnSettings");
const statusLeft = document.getElementById("statusLeft");
const robotTxt = document.getElementById("robotTxt");
const movesTxt = document.getElementById("movesTxt");
const scoreR = document.getElementById("scoreR");
const scoreY = document.getElementById("scoreY");
const progressFill = document.getElementById("progressFill");
const progressTxt = document.getElementById("progressTxt");

let state = null;
let autoplayTimer = null;

function buildColNums(cols) {
    colnumsEl.innerHTML = "";
    for (let i = 1; i <= cols; i++) {
        const d = document.createElement("div");
        d.textContent = String(i);
        colnumsEl.appendChild(d);
    }
}

function render() {
    if (!state) return;

    buildColNums(state.cols);

    // status line déjà formaté par backend (copie de ton controller)
    statusLeft.textContent = state.status_text;

    robotTxt.textContent = state.robot_algo;
    movesTxt.textContent = `${state.cursor}/${state.total}`;
    progressTxt.textContent = `${state.cursor}/${state.total}`;
    const totalSlots = state.rows * state.cols;
    progressFill.style.width = `${(state.cursor / Math.max(1, totalSlots)) * 100}%`;

    scoreR.textContent = String(state.match_score.R);
    scoreY.textContent = String(state.match_score.Y);

    // render grid
    boardEl.innerHTML = "";
    boardEl.style.gridTemplateColumns = `repeat(${state.cols}, var(--cell))`;
    boardEl.style.gridTemplateRows = `repeat(${state.rows}, var(--cell))`;

    for (let r = 0; r < state.rows; r++) {
        for (let c = 0; c < state.cols; c++) {
            const cell = document.createElement("div");
            cell.className = "cell";
            const v = state.board[r][c];
            if (v === "R") cell.classList.add("red");
            if (v === "Y") cell.classList.add("yellow");
            cell.addEventListener("click", () => onColClick(c));
            boardEl.appendChild(cell);
        }
    }
}

async function refresh() {
    state = await api("/api/state");
    // sync UI selects
    modeEl.value = String(state.mode);
    robotEl.value = state.robot_algo.toLowerCase() === "minimax" ? "minimax" : "random";
    depthEl.value = String(state.robot_depth);
    render();
    maybeAutoplay();
}

async function onColClick(col) {
    try {
        await api("/api/move", "POST", { col });
        await refresh();
    } catch (e) {
        // ignore invalid moves
        console.log(e.message);
    }
}

function stopAutoplay() {
    if (autoplayTimer) {
        clearInterval(autoplayTimer);
        autoplayTimer = null;
    }
}

let autoplayRunning = false;

function maybeAutoplay() {
    stopAutoplay();
    if (!state) return;
    if (state.paused || state.finished) return;

    const mode = state.mode;
    const turn = state.current_turn;

    const needAI = (mode === 0) || (mode === 1 && turn === "Y");
    if (!needAI) return;

    autoplayRunning = true;

    // boucle "safe": ne relance pas tant que la requête n'est pas finie
    (async function loop() {
        while (autoplayRunning) {
            try {
                await api("/api/step_ai", "POST");
                await refresh();
            } catch (e) {
                autoplayRunning = false;
                break;
            }

            // petite pause entre coups (évite de saturer)
            await new Promise((r) => setTimeout(r, 350));
            if (!state || state.paused || state.finished) {
                autoplayRunning = false;
            }
        }
    })();
}

function stopAutoplay() {
    autoplayRunning = false;
}

// --- events ---
btnNew.addEventListener("click", async() => {
    await api("/api/new", "POST");
    await refresh();
});

btnPause.addEventListener("click", async() => {
    await api("/api/pause", "POST");
    await refresh();
});

btnPrev.addEventListener("click", async() => {
    await api("/api/undo", "POST");
    await refresh();
});

btnNext.addEventListener("click", async() => {
    await api("/api/redo", "POST");
    await refresh();
});

modeEl.addEventListener("change", async() => {
    await api("/api/set", "POST", { mode: Number(modeEl.value) });
    await refresh();
});

robotEl.addEventListener("change", async() => {
    await api("/api/set", "POST", { robot_algo: robotEl.value });
    await refresh();
});

depthEl.addEventListener("change", async() => {
    await api("/api/set", "POST", { robot_depth: Number(depthEl.value) });
    await refresh();
});
btnSave.addEventListener("click", async() => {
    const snap = await api("/api/save");
    const blob = new Blob([JSON.stringify(snap, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `partie_${state?.game_index ?? "save"}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
});
btnLoad.addEventListener("click", async() => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json,application/json";
    input.onchange = async() => {
        const file = (input.files && input.files[0]) ? input.files[0] : null;
        if (!file) return;
        const text = await file.text();
        const snapshot = JSON.parse(text);
        await api("/api/load", "POST", { snapshot });
        await refresh();
    };
    input.click();
});
btnLoadDb.addEventListener("click", async() => {
    try {
        const data = await api("/api/db/list");
        const games = data.games || [];
        if (!games.length) return alert("Aucune partie en DB.");

        // on affiche les 15 dernières en texte
        const last = games.slice(0, 15).map(g =>
            `#${g.id} | ${g.status} | seq=${(g.original_sequence||"").slice(0,25)} | src=${g.source_filename||""}`
        ).join("\n");

        const idStr = prompt("Entrez l'ID d'une partie à charger.\n\nDernières:\n" + last);
        if (!idStr) return;
        const gid = Number(idStr);
        if (!Number.isFinite(gid)) return;

        await api(`/api/db/load/${gid}`, "POST");
        await refresh();
    } catch (e) {
        alert("DB non disponible / erreur.\n" + e.message);
    }
});
btnSettings.addEventListener("click", async() => {
    const cfg = await api("/api/config");
    const rows = Number(prompt("rows (4..30)", cfg.rows));
    const cols = Number(prompt("cols (4..30)", cfg.cols));
    const starting_color = prompt("starting_color (R ou Y)", cfg.starting_color) || cfg.starting_color;
    const cell_size = Number(prompt("cell_size (30..120)", cfg.cell_size));
    const margin = Number(prompt("margin (5..50)", cfg.margin));
    const drop_delay_ms = Number(prompt("drop_delay_ms (0..2000)", cfg.drop_delay_ms));

    await api("/api/config", "POST", { rows, cols, starting_color, cell_size, margin, drop_delay_ms });
    await api("/api/new", "POST"); // recrée partie sur config
    await refresh();
});
// boot
refresh();