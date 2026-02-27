async function api(path, method = "GET", body = null) {
    const opts = { method, headers: {} };
    if (body) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);

    const text = await res.text();
    let data = null;
    try {
        data = JSON.parse(text);
    } catch {
        throw new Error(`API non-JSON (${res.status}) : ${text.slice(0, 120)}`);
    }

    if (!res.ok) throw new Error(data.detail || "API error");
    return data;
}

// helpers (0 optional chaining)
function on(el, event, handler) { if (el) el.addEventListener(event, handler); }

function removeClass(el, cls) { if (el) el.classList.remove(cls); }

function addClass(el, cls) { if (el) el.classList.add(cls); }

function setText(el, txt) { if (el) el.textContent = txt; }

// DOM
const boardEl = document.getElementById("board");
const colnumsEl = document.getElementById("colnums");
const ghostEl = document.getElementById("ghost");

const movesListEl = document.getElementById("movesList");
const movesMetaEl = document.getElementById("movesMeta");

const winnerModal = document.getElementById("winnerModal");
const winnerTitle = document.getElementById("winnerTitle");
const winnerText = document.getElementById("winnerText");
const btnCloseWinner = document.getElementById("btnCloseWinner");
const btnNewFromWinner = document.getElementById("btnNewFromWinner");

const modeEl = document.getElementById("mode");
const robotEl = document.getElementById("robot");
const depthEl = document.getElementById("depth");

const btnNew = document.getElementById("btnNew");
const btnPause = document.getElementById("btnPause");
const btnPrev = document.getElementById("btnPrev");
const btnNext = document.getElementById("btnNext");

// ✅ Save/Load supprimés => pas de btnSave / btnLoad

// ✅ DB gardé mais renommé en “Parties précédentes”
const btnLoadDb = document.getElementById("btnLoadDb");

const btnSettings = document.getElementById("btnSettings");

const statusLeft = document.getElementById("statusLeft");
const robotTxt = document.getElementById("robotTxt");
const movesTxt = document.getElementById("movesTxt");
const scoreR = document.getElementById("scoreR");
const scoreY = document.getElementById("scoreY");
const progressFill = document.getElementById("progressFill");
const progressTxt = document.getElementById("progressTxt");

// state
let state = null;
let autoplayRunning = false;
let hoveredCol = null;

// colnums aligned with board
function buildColNums(cols) {
    if (!colnumsEl) return;

    colnumsEl.innerHTML = "";
    colnumsEl.style.gridTemplateColumns = `repeat(${cols}, var(--cell))`;
    colnumsEl.style.width = "fit-content";

    for (let i = 1; i <= cols; i++) {
        const d = document.createElement("div");
        d.textContent = String(i);
        colnumsEl.appendChild(d);
    }
}

function setHoverCol(c) {
    hoveredCol = c;
    highlightColumn();
    updateGhost();
}

function highlightColumn() {
    const els = document.querySelectorAll(".cell.col-hover");
    for (let i = 0; i < els.length; i++) els[i].classList.remove("col-hover");

    if (hoveredCol === null) return;

    const colEls = document.querySelectorAll(`.cell[data-col="${hoveredCol}"]`);
    for (let i = 0; i < colEls.length; i++) colEls[i].classList.add("col-hover");
}

function hideGhost() {
    if (!ghostEl) return;
    ghostEl.style.transform = "translateX(-9999px)";
    ghostEl.classList.remove("red", "yellow");
}

function updateGhost() {
    if (!ghostEl || hoveredCol === null || !state || state.finished || state.paused) {
        hideGhost();
        return;
    }

    // colonne pleine => pas de ghost
    if (state.board && state.board[0] && state.board[0][hoveredCol] !== ".") {
        hideGhost();
        return;
    }

    ghostEl.classList.toggle("red", state.current_turn === "R");
    ghostEl.classList.toggle("yellow", state.current_turn === "Y");

    if (!boardEl) {
        hideGhost();
        return;
    }

    const padLeft = parseFloat(getComputedStyle(boardEl).paddingLeft) || 16;
    const padTop = parseFloat(getComputedStyle(boardEl).paddingTop) || 16;
    const gap = parseFloat(getComputedStyle(boardEl).gap) || 12;

    const cell = getComputedStyle(document.documentElement).getPropertyValue("--cell").trim();
    const cellPx = Number(cell.replace("px", "")) || 64;

    let colH = 40;
    if (colnumsEl && typeof colnumsEl.offsetHeight === "number") colH = colnumsEl.offsetHeight;

    const top = colH + (padTop - cellPx * 0.55);
    ghostEl.style.top = `${Math.max(0, top)}px`;

    const x = padLeft + hoveredCol * (cellPx + gap);
    ghostEl.style.transform = `translateX(${x}px)`;
}

function renderMoves() {
    if (!movesListEl || !state) return;

    const moves = state.moves || [];
    setText(movesMetaEl, `${moves.length} coup(s)`);

    movesListEl.innerHTML = "";
    for (let i = moves.length - 1; i >= 0; i--) {
        const mv = moves[i];
        const li = document.createElement("li");

        const left = document.createElement("div");
        left.className = "left";

        const dot = document.createElement("div");
        dot.className = "dot " + (mv.color === "R" ? "red" : "yellow");

        const txt = document.createElement("div");
        txt.textContent = `${mv.color === "R" ? "Rouge" : "Jaune"} → Col ${mv.col + 1}`;

        left.appendChild(dot);
        left.appendChild(txt);

        const badge = document.createElement("div");
        badge.className = "badge";
        badge.textContent = `#${mv.ply}`;

        li.appendChild(left);
        li.appendChild(badge);
        movesListEl.appendChild(li);
    }
}

function renderWinnerModal() {
    if (!winnerModal || !state) return;

    if (!state.finished) {
        winnerModal.classList.remove("show");
        return;
    }

    addClass(winnerModal, "show");
    setText(winnerTitle, "Fin de partie");

    if (state.draw) {
        setText(winnerText, "Égalité 🤝");
    } else if (state.winner === "R") {
        setText(winnerText, "Le gagnant est : Rouge 🔴");
    } else if (state.winner === "Y") {
        setText(winnerText, "Le gagnant est : Jaune 🟡");
    } else {
        setText(winnerText, "Partie terminée.");
    }
}

function render() {
    if (!state) return;

    buildColNums(state.cols);

    setText(statusLeft, state.status_text);
    setText(robotTxt, state.robot_algo);
    setText(movesTxt, `${state.cursor}/${state.total}`);
    setText(progressTxt, `${state.cursor}/${state.total}`);

    const totalSlots = state.rows * state.cols;
    if (progressFill) {
        progressFill.style.width = `${(state.cursor / Math.max(1, totalSlots)) * 100}%`;
    }

    setText(scoreR, String(state.match_score.R));
    setText(scoreY, String(state.match_score.Y));

    if (!boardEl) return;

    boardEl.innerHTML = "";
    boardEl.style.gridTemplateColumns = `repeat(${state.cols}, var(--cell))`;
    boardEl.style.gridTemplateRows = `repeat(${state.rows}, var(--cell))`;

    for (let r = 0; r < state.rows; r++) {
        for (let c = 0; c < state.cols; c++) {
            const cellDiv = document.createElement("div");
            cellDiv.className = "cell";
            cellDiv.dataset.col = String(c);

            const v = state.board[r][c];
            if (v === "R") cellDiv.classList.add("red");
            if (v === "Y") cellDiv.classList.add("yellow");
            if (hoveredCol === c) cellDiv.classList.add("col-hover");

            cellDiv.addEventListener("click", () => onColClick(c));
            cellDiv.addEventListener("mouseenter", () => setHoverCol(c));
            cellDiv.addEventListener("mouseleave", () => setHoverCol(null));

            boardEl.appendChild(cellDiv);
        }
    }

    renderMoves();
    renderWinnerModal();
    updateGhost();
}

async function refresh() {
    state = await api("/api/state");

    if (modeEl) modeEl.value = String(state.mode);
    if (robotEl) robotEl.value = state.robot_algo.toLowerCase() === "minimax" ? "minimax" : "random";
    if (depthEl) depthEl.value = String(state.robot_depth);

    render();
    maybeAutoplay();
}

// ✅ SANS animation: click -> API -> refresh
async function onColClick(col) {
    try {
        await api("/api/move", "POST", { col });
        await refresh();
    } catch (e) {
        console.log(e.message);
    }
}

function stopAutoplay() { autoplayRunning = false; }

function maybeAutoplay() {
    stopAutoplay();
    if (!state) return;
    if (state.paused || state.finished) return;

    const mode = state.mode;
    const turn = state.current_turn;
    const needAI = mode === 0 || (mode === 1 && turn === "Y");
    if (!needAI) return;

    autoplayRunning = true;

    (async function loop() {
        while (autoplayRunning) {
            try {
                await api("/api/step_ai", "POST");
                await refresh();
            } catch (e) {
                autoplayRunning = false;
                break;
            }

            await new Promise((r) => setTimeout(r, 350));
            if (!state || state.paused || state.finished) autoplayRunning = false;
        }
    })();
}

// events
on(btnNew, "click", async() => {
    await api("/api/new", "POST");
    hoveredCol = null;
    await refresh();
});

on(btnPause, "click", async() => {
    await api("/api/pause", "POST");
    await refresh();
});

on(btnPrev, "click", async() => {
    await api("/api/undo", "POST");
    await refresh();
});

on(btnNext, "click", async() => {
    await api("/api/redo", "POST");
    await refresh();
});

on(modeEl, "change", async() => {
    await api("/api/set", "POST", { mode: Number(modeEl.value) });
    await refresh();
});

on(robotEl, "change", async() => {
    await api("/api/set", "POST", { robot_algo: robotEl.value });
    await refresh();
});

on(depthEl, "change", async() => {
    await api("/api/set", "POST", { robot_depth: Number(depthEl.value) });
    await refresh();
});

// ✅ Parties précédentes (DB) : garde la logique DB
on(btnLoadDb, "click", async() => {
    try {
        const data = await api("/api/db/list");
        const games = data.games || [];
        if (!games.length) return alert("Aucune partie enregistrée.");

        const last = games
            .slice(0, 15)
            .map((g) => {
                const seq = (g.original_sequence || "").slice(0, 25);
                const src = g.source_filename || "";
                return `#${g.id} | ${g.status} | seq=${seq} | src=${src}`;
            })
            .join("\n");

        const idStr = prompt("Choisis l'ID d'une partie à charger.\n\nDernières parties:\n" + last);
        if (!idStr) return;
        const gid = Number(idStr);
        if (!Number.isFinite(gid)) return;

        await api(`/api/db/load/${gid}`, "POST");
        await refresh();
    } catch (e) {
        alert("DB non disponible / erreur.\n" + e.message);
    }
});

on(btnSettings, "click", async() => {
    const cfg = await api("/api/config");
    const rows = Number(prompt("rows (4..30)", cfg.rows));
    const cols = Number(prompt("cols (4..30)", cfg.cols));
    const starting_color = prompt("starting_color (R ou Y)", cfg.starting_color) || cfg.starting_color;
    const cell_size = Number(prompt("cell_size (30..120)", cfg.cell_size));
    const margin = Number(prompt("margin (5..50)", cfg.margin));
    const drop_delay_ms = Number(prompt("drop_delay_ms (0..2000)", cfg.drop_delay_ms));

    await api("/api/config", "POST", { rows, cols, starting_color, cell_size, margin, drop_delay_ms });
    await api("/api/new", "POST");
    await refresh();
});

// modal buttons
on(btnCloseWinner, "click", () => removeClass(winnerModal, "show"));

on(btnNewFromWinner, "click", async() => {
    removeClass(winnerModal, "show");
    await api("/api/new", "POST");
    hoveredCol = null;
    await refresh();
});

// boot
refresh();
