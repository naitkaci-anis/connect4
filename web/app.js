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

// helpers
function on(el, event, handler) {
    if (el) el.addEventListener(event, handler);
}

function removeClass(el, cls) {
    if (el) el.classList.remove(cls);
}

function addClass(el, cls) {
    if (el) el.classList.add(cls);
}

function setText(el, txt) {
    if (el) el.textContent = txt;
}

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
const btnLoadDb = document.getElementById("btnLoadDb");
const btnSettings = document.getElementById("btnSettings");

const bgaTableIdEl = document.getElementById("bgaTableId");
const btnImportBga = document.getElementById("btnImportBga");

const statusLeft = document.getElementById("statusLeft");
const robotTxt = document.getElementById("robotTxt");
const movesTxt = document.getElementById("movesTxt");
const scoreR = document.getElementById("scoreR");
const scoreY = document.getElementById("scoreY");
const progressFill = document.getElementById("progressFill");
const progressTxt = document.getElementById("progressTxt");

const onlineConsoleEl = document.getElementById("onlineConsole");

// state
let state = null;
let autoplayRunning = false;
let stepAiInFlight = false;
let hoveredCol = null;

// online state
let onlineMode = false;
let onlineRoomId = null;
let onlinePlayerToken = null;
let onlineColor = null;
let onlinePollingHandle = null;

// winner modal anti-loop
let lastFinishedSignature = null;

// console anti-spam
let lastConsoleSignature = null;

// ============================================================
// CONSOLE HELPERS
// ============================================================

function clearConsole() {
    if (!onlineConsoleEl) return;
    onlineConsoleEl.innerHTML = "";
}

function pushConsoleMessage(text, type = "info") {
    if (!onlineConsoleEl) return;

    const line = document.createElement("div");
    line.className = "console-line " + type;
    line.textContent = text;

    onlineConsoleEl.prepend(line);

    while (onlineConsoleEl.children.length > 12) {
        onlineConsoleEl.removeChild(onlineConsoleEl.lastChild);
    }
}

function pushConsoleMessageOnce(signature, text, type = "info") {
    if (lastConsoleSignature === signature) return;
    lastConsoleSignature = signature;
    pushConsoleMessage(text, type);
}

// ============================================================
// ONLINE HELPERS
// ============================================================

function stopOnlinePolling() {
    if (onlinePollingHandle) {
        clearInterval(onlinePollingHandle);
        onlinePollingHandle = null;
    }
}

function startOnlinePolling() {
    stopOnlinePolling();

    if (!onlineMode || !onlineRoomId || !onlinePlayerToken) return;

    onlinePollingHandle = setInterval(async() => {
        try {
            await refresh();
        } catch (e) {
            console.error("online polling failed:", e);
        }
    }, 1500);
}

async function joinOnlineMatch() {
    const data = await api("/api/online/join", "POST", {});

    onlineMode = true;
    onlineRoomId = data.room_id;
    onlinePlayerToken = data.player_token;
    onlineColor = data.color || null;

    clearConsole();
    lastConsoleSignature = null;
    lastFinishedSignature = null;

    if (onlineColor === "R") {
        pushConsoleMessage("Tu es le joueur Rouge.", "success");
    } else if (onlineColor === "Y") {
        pushConsoleMessage("Tu es le joueur Jaune.", "success");
    }

    if (data.waiting) {
        pushConsoleMessage("En attente d'un adversaire...", "warn");
        setText(statusLeft, `En attente d'un adversaire... (${onlineColor || "?"})`);
    } else {
        pushConsoleMessage("Adversaire trouvé. La partie commence.", "success");
        setText(statusLeft, `Partie en ligne • Tu es ${onlineColor === "R" ? "Rouge" : "Jaune"}`);
    }

    startOnlinePolling();
    await refresh();
}

async function refreshOnline() {
    if (!onlineRoomId || !onlinePlayerToken) {
        throw new Error("Session online incomplète");
    }

    state = await api(
        `/api/online/state?room_id=${encodeURIComponent(onlineRoomId)}&player_token=${encodeURIComponent(onlinePlayerToken)}`
    );

    if (modeEl) modeEl.value = "3";
    render();
}

async function playOnlineMove(col) {
    if (!onlineRoomId || !onlinePlayerToken) {
        throw new Error("Session online incomplète");
    }

    await api("/api/online/move", "POST", {
        room_id: onlineRoomId,
        player_token: onlinePlayerToken,
        col
    });

    await refresh();
}

// ============================================================
// RENDER HELPERS
// ============================================================

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
    for (let i = 0; i < els.length; i++) {
        els[i].classList.remove("col-hover");
    }

    if (hoveredCol === null) return;

    const colEls = document.querySelectorAll(`.cell[data-col="${hoveredCol}"]`);
    for (let i = 0; i < colEls.length; i++) {
        colEls[i].classList.add("col-hover");
    }
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

    if (state.board && state.board[0] && state.board[0][hoveredCol] !== ".") {
        hideGhost();
        return;
    }

    if (onlineMode && onlineColor && state.current_turn !== onlineColor) {
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
    if (colnumsEl && typeof colnumsEl.offsetHeight === "number") {
        colH = colnumsEl.offsetHeight;
    }

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

function updateOnlineConsoleFromState() {
    if (!onlineMode || !state) return;

    const waiting = state.online && state.online.waiting;
    const total = state.total || 0;

    if (waiting) {
        pushConsoleMessageOnce(
            `waiting|${onlineRoomId}|${total}`,
            "En attente d'un adversaire...",
            "warn"
        );
        return;
    }

    if (total === 0) {
        pushConsoleMessageOnce(
            `start|${onlineRoomId}`,
            "Adversaire trouvé. La partie commence.",
            "success"
        );
    }

    if (state.finished) {
        if (state.draw) {
            pushConsoleMessageOnce(
                `finish|draw|${state.total}`,
                "La partie est terminée : égalité.",
                "warn"
            );
        } else if (state.winner === onlineColor) {
            pushConsoleMessageOnce(
                `finish|win|${state.total}`,
                "Bravo, tu as gagné la partie.",
                "success"
            );
        } else {
            pushConsoleMessageOnce(
                `finish|lose|${state.total}`,
                "La partie est terminée. Tu as perdu.",
                "danger"
            );
        }
        return;
    }

    if (state.current_turn === onlineColor) {
        pushConsoleMessageOnce(
            `turn|mine|${state.total}|${state.current_turn}`,
            "C'est à toi de jouer.",
            "success"
        );
    } else {
        pushConsoleMessageOnce(
            `turn|other|${state.total}|${state.current_turn}`,
            "Tour de l'adversaire...",
            "info"
        );
    }
}

function renderWinnerModal() {
    if (!winnerModal || !state) return;

    if (!state.finished) {
        winnerModal.classList.remove("show");
        lastFinishedSignature = null;
        return;
    }

    const sig = `${state.game_index}|${state.winner}|${state.draw}|${state.total}`;

    if (lastFinishedSignature === sig) {
        return;
    }

    lastFinishedSignature = sig;

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

    let statusText = state.status_text;
    if (onlineMode && onlineColor) {
        const colorTxt = onlineColor === "R" ? "Rouge" : "Jaune";
        statusText = `[Online] Tu es ${colorTxt} • ${state.status_text}`;
    }

    setText(statusLeft, statusText);
    setText(robotTxt, state.robot_algo || "-");
    setText(movesTxt, `${state.cursor}/${state.total}`);
    setText(progressTxt, `${state.cursor}/${state.total}`);

    const totalSlots = state.rows * state.cols;
    if (progressFill) {
        progressFill.style.width = `${(state.cursor / Math.max(1, totalSlots)) * 100}%`;
    }

    if (state.match_score) {
        setText(scoreR, String(state.match_score.R));
        setText(scoreY, String(state.match_score.Y));
    }

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

    if (onlineMode) {
        updateOnlineConsoleFromState();
    }

    renderWinnerModal();
    updateGhost();
}

async function refresh() {
    try {
        if (onlineMode) {
            await refreshOnline();
        } else {
            state = await api("/api/state");

            if (modeEl) modeEl.value = String(state.mode);
            if (robotEl) {
                robotEl.value = state.robot_algo.toLowerCase() === "minimax" ? "minimax" : "random";
            }
            if (depthEl) depthEl.value = String(state.robot_depth);

            render();
        }
    } catch (e) {
        console.error("refresh failed:", e);
        setText(statusLeft, "Erreur de chargement");
        alert("Erreur chargement état du jeu : " + e.message);
    }
}

// click -> API -> refresh
async function onColClick(col) {
    try {
        if (onlineMode) {
            await playOnlineMove(col);
            return;
        }

        await api("/api/move", "POST", { col });
        await refresh();
        await maybeAutoplay();
    } catch (e) {
        console.log(e.message);
    }
}

function stopAutoplay() {
    autoplayRunning = false;
}

async function stepAIOnce() {
    if (stepAiInFlight) return false;
    stepAiInFlight = true;

    try {
        await api("/api/step_ai", "POST");
        return true;
    } catch (e) {
        console.error("step_ai failed:", e);
        return false;
    } finally {
        stepAiInFlight = false;
    }
}

async function maybeAutoplay() {
    if (autoplayRunning) return;
    if (!state) return;
    if (state.paused || state.finished) return;
    if (onlineMode) return;

    const needAI = state.mode === 0 || (state.mode === 1 && state.current_turn === "Y");
    if (!needAI) return;

    autoplayRunning = true;

    try {
        while (autoplayRunning) {
            if (!state || state.paused || state.finished || onlineMode) break;

            const stillNeedAI =
                state.mode === 0 || (state.mode === 1 && state.current_turn === "Y");

            if (!stillNeedAI) break;

            const ok = await stepAIOnce();
            if (!ok) break;

            await refresh();

            if (!state || state.paused || state.finished || onlineMode) break;

            await new Promise((r) => setTimeout(r, 350));
        }
    } finally {
        autoplayRunning = false;
    }
}

// events
on(btnNew, "click", async() => {
    stopAutoplay();

    onlineMode = false;
    onlineRoomId = null;
    onlinePlayerToken = null;
    onlineColor = null;
    stopOnlinePolling();
    lastConsoleSignature = null;
    lastFinishedSignature = null;

    if (onlineConsoleEl) {
        clearConsole();
        pushConsoleMessage("Nouvelle partie locale lancée.", "info");
    }

    await api("/api/new", "POST");
    hoveredCol = null;
    await refresh();
    await maybeAutoplay();
});

on(btnPause, "click", async() => {
    if (onlineMode) return;
    await api("/api/pause", "POST");
    await refresh();
    await maybeAutoplay();
});

on(btnPrev, "click", async() => {
    if (onlineMode) return;
    stopAutoplay();
    await api("/api/undo", "POST");
    await refresh();
    await maybeAutoplay();
});

on(btnNext, "click", async() => {
    if (onlineMode) return;
    stopAutoplay();
    await api("/api/redo", "POST");
    await refresh();
    await maybeAutoplay();
});

on(modeEl, "change", async() => {
    const mode = Number(modeEl.value);

    if (mode === 3) {
        stopAutoplay();
        try {
            await joinOnlineMatch();
        } catch (e) {
            onlineMode = false;
            stopOnlinePolling();
            alert("Impossible de lancer le mode en ligne.\n" + e.message);
            await refresh();
        }
        return;
    }

    stopAutoplay();

    onlineMode = false;
    onlineRoomId = null;
    onlinePlayerToken = null;
    onlineColor = null;
    stopOnlinePolling();
    lastConsoleSignature = null;
    lastFinishedSignature = null;

    await api("/api/set", "POST", { mode });
    await refresh();
    await maybeAutoplay();
});

on(robotEl, "change", async() => {
    if (onlineMode) return;
    stopAutoplay();
    await api("/api/set", "POST", { robot_algo: robotEl.value });
    await refresh();
    await maybeAutoplay();
});

on(depthEl, "change", async() => {
    if (onlineMode) return;
    stopAutoplay();
    await api("/api/set", "POST", { robot_depth: Number(depthEl.value) });
    await refresh();
    await maybeAutoplay();
});

// Import BGA
on(btnImportBga, "click", async() => {
    try {
        const raw = bgaTableIdEl ? bgaTableIdEl.value.trim() : "";
        if (!raw) {
            alert("Saisis un numéro de table BGA.");
            return;
        }

        const tableId = Number(raw);
        if (!Number.isFinite(tableId) || tableId <= 0) {
            alert("Numéro de table invalide.");
            return;
        }

        stopAutoplay();

        onlineMode = false;
        onlineRoomId = null;
        onlinePlayerToken = null;
        onlineColor = null;
        stopOnlinePolling();
        lastConsoleSignature = null;
        lastFinishedSignature = null;

        if (onlineConsoleEl) {
            clearConsole();
            pushConsoleMessage(`Import de la table BGA ${tableId}...`, "info");
        }

        await api("/api/bga/load_table", "POST", { table_id: tableId });
        hoveredCol = null;
        await refresh();
        await maybeAutoplay();
    } catch (e) {
        alert("Impossible d'importer la table BGA.\n" + e.message);
    }
});

on(bgaTableIdEl, "keydown", async(ev) => {
    if (ev.key !== "Enter") return;

    try {
        const raw = bgaTableIdEl ? bgaTableIdEl.value.trim() : "";
        if (!raw) {
            alert("Saisis un numéro de table BGA.");
            return;
        }

        const tableId = Number(raw);
        if (!Number.isFinite(tableId) || tableId <= 0) {
            alert("Numéro de table invalide.");
            return;
        }

        stopAutoplay();

        onlineMode = false;
        onlineRoomId = null;
        onlinePlayerToken = null;
        onlineColor = null;
        stopOnlinePolling();
        lastConsoleSignature = null;
        lastFinishedSignature = null;

        if (onlineConsoleEl) {
            clearConsole();
            pushConsoleMessage(`Import de la table BGA ${tableId}...`, "info");
        }

        await api("/api/bga/load_table", "POST", { table_id: tableId });
        hoveredCol = null;
        await refresh();
        await maybeAutoplay();
    } catch (e) {
        alert("Impossible d'importer la table BGA.\n" + e.message);
    }
});

// Parties précédentes (DB)
on(btnLoadDb, "click", async() => {
    try {
        const data = await api("/api/db/list");
        const games = data.games || [];
        if (!games.length) {
            alert("Aucune partie enregistrée.");
            return;
        }

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

        stopAutoplay();

        onlineMode = false;
        onlineRoomId = null;
        onlinePlayerToken = null;
        onlineColor = null;
        stopOnlinePolling();
        lastConsoleSignature = null;
        lastFinishedSignature = null;

        if (onlineConsoleEl) {
            clearConsole();
            pushConsoleMessage(`Chargement de la partie #${gid}...`, "info");
        }

        await api(`/api/db/load/${gid}`, "POST");
        await refresh();
        await maybeAutoplay();
    } catch (e) {
        alert("DB non disponible / erreur.\n" + e.message);
    }
});

on(btnSettings, "click", async() => {
    if (onlineMode) return;

    stopAutoplay();

    const cfg = await api("/api/config");
    const rows = Number(prompt("rows (4..30)", cfg.rows));
    const cols = Number(prompt("cols (4..30)", cfg.cols));
    const starting_color = prompt("starting_color (R ou Y)", cfg.starting_color) || cfg.starting_color;
    const cell_size = Number(prompt("cell_size (30..120)", cfg.cell_size));
    const margin = Number(prompt("margin (5..50)", cfg.margin));
    const drop_delay_ms = Number(prompt("drop_delay_ms (0..2000)", cfg.drop_delay_ms));

    await api("/api/config", "POST", {
        rows,
        cols,
        starting_color,
        cell_size,
        margin,
        drop_delay_ms
    });

    await api("/api/new", "POST");
    await refresh();
    await maybeAutoplay();
});

// modal buttons
on(btnCloseWinner, "click", () => {
    removeClass(winnerModal, "show");
});

on(btnNewFromWinner, "click", async() => {
    removeClass(winnerModal, "show");

    if (onlineMode) {
        pushConsoleMessage("Partie terminée. Pour rejouer en ligne, relance le mode En ligne.", "warn");
        return;
    }

    stopAutoplay();
    lastFinishedSignature = null;
    await api("/api/new", "POST");
    hoveredCol = null;
    await refresh();
    await maybeAutoplay();
});

// boot
if (onlineConsoleEl) {
    clearConsole();
    pushConsoleMessage("Bienvenue sur Puissance 4.", "info");
}

refresh().then(() => maybeAutoplay());
