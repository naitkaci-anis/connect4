// ============================================================
// API helper
// ============================================================
async function api(url, method = "GET", body = null) {
    const options = { method, headers: {} };
    if (body !== null) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
    }
    const res = await fetch(url, options);
    const text = await res.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; } catch (err) { throw new Error("Réponse non JSON : " + text); }
    if (!res.ok) throw new Error(data.detail || data.error || ("HTTP " + res.status));
    return data;
}

// ============================================================
// Helpers DOM
// ============================================================
function on(el, event, handler) { if (el) el.addEventListener(event, handler); }

function removeClass(el, cls) { if (el) el.classList.remove(cls); }

function addClass(el, cls) { if (el) el.classList.add(cls); }

function setText(el, txt) { if (el) el.textContent = txt; }

// ============================================================
// Références DOM
// ============================================================
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
const aiStartsEl = document.getElementById("aiStarts");
const aiStartsGroup = document.getElementById("aiStartsGroup");
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
const btnPaint = document.getElementById("btnPaint");
const btnPredict = document.getElementById("btnPredict");
const paintModal = document.getElementById("paintModal");
const paintBoardEl = document.getElementById("paintBoard");
const paintBrushEl = document.getElementById("paintBrush");
const btnPaintClear = document.getElementById("btnPaintClear");
const btnPaintCancel = document.getElementById("btnPaintCancel");
const btnPaintApply = document.getElementById("btnPaintApply");
const predictBanner = document.getElementById("predictBanner");
const predictTextEl = document.getElementById("predictText");
const btnClosePrediction = document.getElementById("btnClosePrediction");
const aiThinkingBar = document.getElementById("aiThinkingBar");
const aiThinkingTxt = document.getElementById("aiThinkingTxt");
const aiThinkingFill = document.getElementById("aiThinkingFill");

// ============================================================
// State
// ============================================================
let paintGrid = null;
let _aiThinkingInterval = null;
let _aiThinkingStart = 0;
let state = null;
let autoplayRunning = false;
let stepAiInFlight = false;
let hoveredCol = null;
let onlineMode = false;
let onlineRoomId = null;
let onlinePlayerToken = null;
let onlineColor = null;
let onlinePollingHandle = null;
let lastFinishedSignature = null;
let lastConsoleSignature = null;

// ============================================================
// Helpers
// ============================================================
function aiStarts() {
    return aiStartsEl && aiStartsEl.value === "true";
}

function updateAiStartsVisibility() {
    if (!aiStartsGroup) return;
    aiStartsGroup.style.display = (modeEl && Number(modeEl.value) === 1) ? "flex" : "none";
}

// Convertit la valeur du select robot vers la valeur serveur
function robotAlgoValue() {
    if (!robotEl) return "random";
    return robotEl.value; // "random" | "minimax" | "strategic"
}

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
    while (onlineConsoleEl.children.length > 12)
        onlineConsoleEl.removeChild(onlineConsoleEl.lastChild);
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
    if (onlinePollingHandle) { clearInterval(onlinePollingHandle);
        onlinePollingHandle = null; }
}

function startOnlinePolling() {
    stopOnlinePolling();
    if (!onlineMode || !onlineRoomId || !onlinePlayerToken) return;
    onlinePollingHandle = setInterval(async() => {
        try { await refresh(); } catch (e) { console.error("online polling failed:", e); }
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
    if (onlineColor === "R") pushConsoleMessage("Tu es le joueur Rouge.", "success");
    else if (onlineColor === "Y") pushConsoleMessage("Tu es le joueur Jaune.", "success");
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
    if (!onlineRoomId || !onlinePlayerToken) throw new Error("Session online incomplète");
    state = await api(
        `/api/online/state?room_id=${encodeURIComponent(onlineRoomId)}&player_token=${encodeURIComponent(onlinePlayerToken)}`
    );
    if (modeEl) modeEl.value = "3";
    render();
}
async function playOnlineMove(col) {
    if (!onlineRoomId || !onlinePlayerToken) throw new Error("Session online incomplète");
    await api("/api/online/move", "POST", { room_id: onlineRoomId, player_token: onlinePlayerToken, col });
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

function setHoverCol(c) { hoveredCol = c;
    highlightColumn();
    updateGhost(); }

function highlightColumn() {
    document.querySelectorAll(".cell.col-hover").forEach(el => el.classList.remove("col-hover"));
    if (hoveredCol === null) return;
    document.querySelectorAll(`.cell[data-col="${hoveredCol}"]`).forEach(el => el.classList.add("col-hover"));
}

function hideGhost() {
    if (!ghostEl) return;
    ghostEl.style.transform = "translateX(-9999px)";
    ghostEl.classList.remove("red", "yellow");
}

function updateGhost() {
    if (!ghostEl || hoveredCol === null || !state || state.finished || state.paused) { hideGhost(); return; }
    if (state.board && state.board[0] && state.board[0][hoveredCol] !== ".") { hideGhost(); return; }
    if (onlineMode && onlineColor && state.current_turn !== onlineColor) { hideGhost(); return; }
    ghostEl.classList.toggle("red", state.current_turn === "R");
    ghostEl.classList.toggle("yellow", state.current_turn === "Y");
    if (!boardEl) { hideGhost(); return; }
    const padLeft = parseFloat(getComputedStyle(boardEl).paddingLeft) || 16;
    const padTop = parseFloat(getComputedStyle(boardEl).paddingTop) || 16;
    const gap = parseFloat(getComputedStyle(boardEl).gap) || 12;
    const cell = getComputedStyle(document.documentElement).getPropertyValue("--cell").trim();
    const cellPx = Number(cell.replace("px", "")) || 64;
    const colH = colnumsEl ? colnumsEl.offsetHeight : 40;
    ghostEl.style.top = `${Math.max(0, colH + padTop - cellPx * 0.55)}px`;
    ghostEl.style.transform = `translateX(${padLeft + hoveredCol * (cellPx + gap)}px)`;
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
    if (waiting) { pushConsoleMessageOnce(`waiting|${onlineRoomId}|${total}`, "En attente d'un adversaire...", "warn"); return; }
    if (total === 0) pushConsoleMessageOnce(`start|${onlineRoomId}`, "Adversaire trouvé. La partie commence.", "success");
    if (state.finished) {
        if (state.draw)
            pushConsoleMessageOnce(`finish|draw|${state.total}`, "La partie est terminée : égalité.", "warn");
        else if (state.winner === onlineColor)
            pushConsoleMessageOnce(`finish|win|${state.total}`, "Bravo, tu as gagné la partie.", "success");
        else
            pushConsoleMessageOnce(`finish|lose|${state.total}`, "La partie est terminée. Tu as perdu.", "danger");
        return;
    }
    if (state.current_turn === onlineColor)
        pushConsoleMessageOnce(`turn|mine|${state.total}|${state.current_turn}`, "C'est à toi de jouer.", "success");
    else
        pushConsoleMessageOnce(`turn|other|${state.total}|${state.current_turn}`, "Tour de l'adversaire...", "info");
}

function renderWinnerModal() {
    if (!winnerModal || !state) return;
    if (!state.finished) { winnerModal.classList.remove("show");
        lastFinishedSignature = null; return; }
    const sig = `${state.game_index}|${state.winner}|${state.draw}|${state.total}`;
    if (lastFinishedSignature === sig) return;
    lastFinishedSignature = sig;
    addClass(winnerModal, "show");
    setText(winnerTitle, "Fin de partie");
    if (state.draw) setText(winnerText, "Égalité 🤝");
    else if (state.winner === "R") setText(winnerText, "Le gagnant est : Rouge 🔴");
    else if (state.winner === "Y") setText(winnerText, "Le gagnant est : Jaune 🟡");
    else setText(winnerText, "Partie terminée.");
}

function render() {
    if (!state) return;
    buildColNums(state.cols);
    let statusText = state.status_text;
    if (onlineMode && onlineColor)
        statusText = `[Online] Tu es ${onlineColor === "R" ? "Rouge" : "Jaune"} • ${state.status_text}`;
    setText(statusLeft, statusText);
    setText(robotTxt, state.robot_algo || "-");
    setText(movesTxt, `${state.cursor}/${state.total}`);
    setText(progressTxt, `${state.cursor}/${state.total}`);
    const totalSlots = state.rows * state.cols;
    if (progressFill) progressFill.style.width = `${(state.cursor / Math.max(1, totalSlots)) * 100}%`;
    if (state.match_score) { setText(scoreR, String(state.match_score.R));
        setText(scoreY, String(state.match_score.Y)); }
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
    if (onlineMode) updateOnlineConsoleFromState();
    renderWinnerModal();
    updateGhost();
}

// ============================================================
// REFRESH — synchronise les selects avec l'état serveur
// ============================================================
async function refresh() {
    try {
        if (onlineMode) {
            await refreshOnline();
        } else {
            state = await api("/api/state");
            if (modeEl) modeEl.value = String(state.mode);

            // Synchroniser le select Robot avec l'état serveur
            if (robotEl) {
                const ra = (state.robot_algo || "").toLowerCase();
                if (ra === "strategic") robotEl.value = "strategic";
                else if (ra === "minimax") robotEl.value = "minimax";
                else robotEl.value = "random";
            }

            if (depthEl) depthEl.value = String(state.robot_depth);

            // Synchroniser le select "IA commence" depuis l'état serveur
            if (aiStartsEl && state.ai_starts !== undefined) {
                aiStartsEl.value = state.ai_starts ? "true" : "false";
            }

            updateAiStartsVisibility();
            render();
        }
    } catch (e) {
        console.error("refresh failed:", e);
        setText(statusLeft, "Erreur de chargement");
        alert("Erreur chargement état du jeu : " + e.message);
    }
}

// ============================================================
// COUP HUMAIN — affiché IMMÉDIATEMENT avant l'appel réseau
// ============================================================
async function onColClick(col) {
    try {
        if (onlineMode) { await playOnlineMove(col); return; }
        if (!state || state.finished || state.paused) return;

        const isHumanTurn =
            state.mode === 2 ||
            (state.mode === 1 && !aiStarts() && state.current_turn === "R") ||
            (state.mode === 1 && aiStarts() && state.current_turn === "Y");

        // Affichage optimiste AVANT le await
        if (isHumanTurn && state.board && state.board[0][col] === ".") {
            let dropRow = -1;
            for (let r = state.rows - 1; r >= 0; r--) {
                if (state.board[r][col] === ".") { dropRow = r; break; }
            }
            if (dropRow >= 0) {
                let rowCount = 0;
                document.querySelectorAll(`.cell[data-col="${col}"]`).forEach(el => {
                    if (rowCount === dropRow)
                        el.classList.add(state.current_turn === "R" ? "red" : "yellow");
                    rowCount++;
                });
            }
        }

        await api("/api/move", "POST", { col });
        await refresh();
        await maybeAutoplay();
    } catch (e) {
        console.log(e.message);
        await refresh();
    }
}

// ============================================================
// AUTOPLAY IA
// ============================================================
function stopAutoplay() { autoplayRunning = false; }

async function stepAIOnce() {
    if (stepAiInFlight) return false;
    stepAiInFlight = true;
    showAiThinking(state ? (state.robot_depth || 7) : 7);
    try {
        await api("/api/step_ai", "POST");
        return true;
    } catch (e) {
        console.error("step_ai failed:", e);
        return false;
    } finally {
        hideAiThinking();
        stepAiInFlight = false;
    }
}

function _needsAI() {
    if (!state || state.paused || state.finished || onlineMode) return false;
    if (state.mode === 0) return true;
    if (state.mode === 1) {
        return (!aiStarts() && state.current_turn === "Y") ||
            (aiStarts() && state.current_turn === "R");
    }
    return false;
}

async function maybeAutoplay() {
    if (autoplayRunning) return;
    if (!_needsAI()) return;
    autoplayRunning = true;
    try {
        while (autoplayRunning) {
            if (!_needsAI()) break;
            const ok = await stepAIOnce();
            if (!ok) break;
            await refresh();
            if (!_needsAI()) break;
            await new Promise(r => setTimeout(r, 200));
        }
    } finally {
        autoplayRunning = false;
    }
}

// ============================================================
// AI THINKING BAR — courbe exponentielle cohérente
// ============================================================
function showAiThinking(depthHint) {
    if (!aiThinkingBar) return;
    aiThinkingBar.style.display = "block";
    if (aiThinkingTxt) aiThinkingTxt.textContent = "L'IA réfléchit…";
    clearInterval(_aiThinkingInterval);
    _aiThinkingStart = Date.now();
    const estimatedMs = Math.min((depthHint || 4) * (depthHint || 4) * 350, 7000);
    _aiThinkingInterval = setInterval(() => {
        const elapsed = Date.now() - _aiThinkingStart;
        const pct = 92 * (1 - Math.exp(-elapsed / (estimatedMs * 0.8)));
        if (aiThinkingFill) aiThinkingFill.style.width = Math.min(pct, 92) + "%";
    }, 80);
}

function hideAiThinking() {
    clearInterval(_aiThinkingInterval);
    _aiThinkingInterval = null;
    if (!aiThinkingBar) return;
    if (aiThinkingFill) aiThinkingFill.style.width = "100%";
    setTimeout(() => {
        aiThinkingBar.style.display = "none";
        if (aiThinkingFill) aiThinkingFill.style.width = "0%";
    }, 180);
}

// ============================================================
// EVENTS
// ============================================================
on(btnNew, "click", async() => {
    stopAutoplay();
    onlineMode = false;
    onlineRoomId = null;
    onlinePlayerToken = null;
    onlineColor = null;
    stopOnlinePolling();
    lastConsoleSignature = null;
    lastFinishedSignature = null;
    clearConsole();
    pushConsoleMessage("Nouvelle partie locale lancée.", "info");
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

// Changement de mode
on(modeEl, "change", async() => {
    const mode = Number(modeEl.value);
    updateAiStartsVisibility();

    if (mode === 3) {
        stopAutoplay();
        try { await joinOnlineMatch(); } catch (e) {
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

// IA commence change
on(aiStartsEl, "change", async() => {
    if (onlineMode) return;
    stopAutoplay();
    lastFinishedSignature = null;

    // 1) Envoyer ai_starts au serveur
    const val = aiStartsEl ? aiStartsEl.value === "true" : false;
    await api("/api/set", "POST", { ai_starts: val });

    // 2) Nouvelle partie pour appliquer
    await api("/api/new", "POST");
    hoveredCol = null;

    await refresh();
    await maybeAutoplay();
});

// Changement de robot (Random / MiniMax / Stratégique)
on(robotEl, "change", async() => {
    if (onlineMode) return;
    stopAutoplay();
    await api("/api/set", "POST", { robot_algo: robotAlgoValue() });
    await refresh();
    await maybeAutoplay();
});

// Changement de profondeur
on(depthEl, "change", async() => {
    if (onlineMode) return;
    stopAutoplay();
    await api("/api/set", "POST", { robot_depth: Number(depthEl.value) });
    await refresh();
    await maybeAutoplay();
});

// Import BGA
async function doImportBga() {
    try {
        const raw = bgaTableIdEl ? bgaTableIdEl.value.trim() : "";
        if (!raw) { alert("Saisis un numéro de table BGA."); return; }
        const tableId = Number(raw);
        if (!Number.isFinite(tableId) || tableId <= 0) { alert("Numéro de table invalide."); return; }
        stopAutoplay();
        onlineMode = false;
        onlineRoomId = null;
        onlinePlayerToken = null;
        onlineColor = null;
        stopOnlinePolling();
        lastConsoleSignature = null;
        lastFinishedSignature = null;
        clearConsole();
        pushConsoleMessage(`Import de la table BGA ${tableId}...`, "info");
        await api("/api/bga/load_table", "POST", { table_id: tableId });
        hoveredCol = null;
        await refresh();
        await maybeAutoplay();
    } catch (e) { alert("Impossible d'importer la table BGA.\n" + e.message); }
}
on(btnImportBga, "click", doImportBga);
on(bgaTableIdEl, "keydown", async(ev) => { if (ev.key === "Enter") await doImportBga(); });

// Parties précédentes (DB)
on(btnLoadDb, "click", async() => {
    try {
        const data = await api("/api/db/list");
        const games = data.games || [];
        if (!games.length) { alert("Aucune partie enregistrée."); return; }
        const last = games.slice(0, 15).map(g =>
            `#${g.id} | ${g.status} | seq=${(g.original_sequence||"").slice(0,25)} | src=${g.source_filename||""}`
        ).join("\n");
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
        clearConsole();
        pushConsoleMessage(`Chargement de la partie #${gid}...`, "info");
        await api(`/api/db/load/${gid}`, "POST");
        await refresh();
        await maybeAutoplay();
    } catch (e) { alert("DB non disponible / erreur.\n" + e.message); }
});

// Paramètres
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
    await api("/api/config", "POST", { rows, cols, starting_color, cell_size, margin, drop_delay_ms });
    await api("/api/new", "POST");
    await refresh();
    await maybeAutoplay();
});

// Modales winner
on(btnCloseWinner, "click", () => { removeClass(winnerModal, "show"); });
on(btnNewFromWinner, "click", async() => {
    removeClass(winnerModal, "show");
    if (onlineMode) { pushConsoleMessage("Pour rejouer en ligne, relance le mode En ligne.", "warn"); return; }
    stopAutoplay();
    lastFinishedSignature = null;
    await api("/api/new", "POST");
    hoveredCol = null;
    await refresh();
    await maybeAutoplay();
});

// ============================================================
// PREDICTION
// ============================================================
on(btnPredict, "click", async() => {
    if (!predictBanner || !predictTextEl) return;
    predictTextEl.textContent = "Analyse en cours...";
    predictBanner.style.display = "flex";
    try {
        const data = await api("/api/predict");
        const colorName = data.winner === "R" ? "Rouge" : data.winner === "Y" ? "Jaune" : null;
        let txt = "";
        if (colorName && typeof data.moves_left === "number" && data.moves_left > 0) {
            const turns = Math.max(1, Math.ceil(data.moves_left / 2));
            txt = "🔮 " + colorName + " gagne dans environ " + turns + " tour(s).";
        } else if (colorName) {
            txt = "🔮 " + colorName + " est en avantage.";
        } else if (data.winner === "draw") {
            txt = "🤝 Partie terminée : égalité.";
        } else if (data.explanation) {
            txt = "🔮 " + data.explanation;
        } else {
            txt = "🔮 Aucune prédiction disponible.";
        }
        predictTextEl.textContent = txt;
    } catch (e) {
        predictTextEl.textContent = "Erreur de prédiction : " + (e && e.message ? e.message : String(e));
    }
});
on(btnClosePrediction, "click", () => {
    if (predictBanner) predictBanner.style.display = "none";
});

// ============================================================
// PAINT & REPRISE
// ============================================================
function buildPaintBoard(rows, cols) {
    if (!paintBoardEl) return;
    paintGrid = Array.from({ length: rows }, () => Array(cols).fill("."));
    paintBoardEl.innerHTML = "";
    paintBoardEl.style.gridTemplateColumns = `repeat(${cols}, 36px)`;
    for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
            const cell = document.createElement("div");
            cell.className = "paint-cell empty";
            cell.dataset.r = r;
            cell.dataset.c = c;
            cell.addEventListener("click", () => {
                const brush = paintBrushEl ? paintBrushEl.value : "R";
                paintGrid[r][c] = brush;
                cell.className = "paint-cell " + (brush === "R" ? "red" : brush === "Y" ? "yellow" : "empty");
                cell.textContent = brush === "." ? "" : brush;
            });
            paintBoardEl.appendChild(cell);
        }
    }
}
on(btnPaint, "click", () => {
    if (!state || !paintModal) return;
    buildPaintBoard(state.rows, state.cols);
    paintModal.classList.add("show");
});
on(btnPaintClear, "click", () => { if (!state) return;
    buildPaintBoard(state.rows, state.cols); });
on(btnPaintCancel, "click", () => { if (paintModal) paintModal.classList.remove("show"); });
on(btnPaintApply, "click", async() => {
    if (!paintGrid) return;
    try {
        const data = await api("/api/paint", "POST", { board: paintGrid });
        if (paintModal) paintModal.classList.remove("show");
        hoveredCol = null;
        if (data.paint_analysis) {
            const turn = data.paint_analysis.current_turn_inferred === "R" ? "Rouge" : "Jaune";
            pushConsoleMessage(`Position chargée — C'est au joueur ${turn} de jouer.`, "success");
        }
        await refresh();
        await maybeAutoplay();
    } catch (e) { alert("Erreur paint : " + e.message); }
});

// ============================================================
// BOOT
// ============================================================
if (onlineConsoleEl) {
    clearConsole();
    pushConsoleMessage("Bienvenue sur Puissance 4.", "info");
}
updateAiStartsVisibility();
refresh().then(() => maybeAutoplay());
