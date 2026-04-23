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
const robotREl = document.getElementById("robotR");
const robotYEl = document.getElementById("robotY");
const robotGroup = document.getElementById("robotGroup");
const robotRGroup = document.getElementById("robotRGroup");
const robotYGroup = document.getElementById("robotYGroup");
const depthEl = document.getElementById("depth");
const depthGroup = document.getElementById("depthGroup");
// Couleur IA — remplace l'ancien "IA commence"
const aiColorEl = document.getElementById("aiColor");
const aiColorGroup = document.getElementById("aiColorGroup");
// Alias de compatibilité (pour les fonctions qui utilisent aiStartsEl)
const aiStartsEl = null; // supprimé — utiliser aiColorEl
const btnNew = document.getElementById("btnNew");
const btnStart = document.getElementById("btnStart");
const btnPause = document.getElementById("btnPause");
const btnPrev = document.getElementById("btnPrev");
const btnNext = document.getElementById("btnNext");
const btnLoadDb = document.getElementById("btnLoadDb");
// btnSettings supprimé
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
const btnImportFile = document.getElementById("btnImportFile");
const fileInput = document.getElementById("fileInput");
const fileInputLabel = document.getElementById("fileInputLabel");
const fileInputName = document.getElementById("fileInputName");
const fileImportOptions = document.getElementById("fileImportOptions");
const btnFileContinueIAvIA = document.getElementById("btnFileContinueIAvIA");
const btnFileContinueJvsIA = document.getElementById("btnFileContinueJvsIA");
const btnFileContinueJvsJ = document.getElementById("btnFileContinueJvsJ");
const paintModal = document.getElementById("paintModal");
const paintBoardEl = document.getElementById("paintBoard");
const paintBrushEl = document.getElementById("paintBrush");
const btnPaintClear = document.getElementById("btnPaintClear");
const btnPaintCancel = document.getElementById("btnPaintCancel");
const btnPaintApply = document.getElementById("btnPaintApply");
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
let moveInFlight = false;
let hoveredCol = null;
let onlineMode = false;
let onlineRoomId = null;
let onlinePlayerToken = null;
let onlineColor = null;
let onlinePollingHandle = null;
let lastFinishedSignature = null;
let lastConsoleSignature = null;
let gameStarted = false; // bloque l'autoplay jusqu'au clic sur ▶ Start

// ============================================================
// NEURAL EVAL AUTO — prédiction neuronale après chaque coup
// ============================================================
let _lastNeuralCursor = -1;

async function neuralEvalUpdate(cursor) {
    if (cursor === _lastNeuralCursor) return;
    _lastNeuralCursor = cursor;

    const label = document.getElementById("neuralEvalLabel");
    const expl = document.getElementById("neuralEvalExpl");
    const barR = document.getElementById("neuralBarRed");
    const barY = document.getElementById("neuralBarYellow");
    const pct = document.getElementById("neuralBarPct");
    if (!label) return;

    try {
        const d = await api("/api/neural_eval");

        const v = (d.value !== null && d.value !== undefined) ? d.value : 0;
        const rPct = Math.round(50 + v * 45);
        const yPct = 100 - rPct;

        if (barR) barR.style.width = rPct + "%";
        if (barY) barY.style.width = yPct + "%";
        if (pct) pct.textContent = `${rPct} / ${yPct}`;

        const icons = { victoire: "✅", defaite: "❌", nul: "🤝", incertain: "🔮", unavailable: "⚠️", error: "⚠️" };
        const colors = {
            victoire: d.color_wins === "R" ? "#ff6b6b" : "#ffe46b",
            defaite: d.color_wins === "R" ? "#ff6b6b" : "#ffe46b",
            nul: "#b8c7ee",
            incertain: "#b8c7ee",
            unavailable: "#888",
            error: "#f87171"
        };
        const texts = {
            victoire: d.color_wins === "R" ? "Victoire Rouge 🔴" : "Victoire Jaune 🟡",
            defaite: d.color_wins === "R" ? "Victoire Rouge 🔴" : "Victoire Jaune 🟡",
            nul: "Match Nul 🤝",
            incertain: "Incertain 🔮",
            unavailable: "Modèle absent",
            error: "Erreur"
        };

        label.textContent = (icons[d.label] || "?") + " " + (texts[d.label] || d.label);
        label.style.color = colors[d.label] || "#eee";
        if (expl) expl.textContent = d.explanation || "";

    } catch (e) {
        if (label) {
            label.textContent = "⚠️ Erreur";
            label.style.color = "#f87171";
        }
    }
}

// ============================================================
// HINT — meilleur coup pour le joueur humain
// ============================================================
let _lastHintCursor = -2;
let _hintData = null;

async function hintUpdate(st) {
    const panel = document.getElementById("hintPanel");
    if (!panel) return;

    // Cacher si partie terminée, mode IA vs IA, ou mode en ligne
    if (!st || st.finished || onlineMode || st.mode === 0) {
        panel.style.display = "none";
        return;
    }

    // Visible uniquement quand c'est le tour d'un humain
    const isHumanTurn =
        st.mode === 2 ||
        (st.mode === 1 && !aiStarts() && st.current_turn === "R") ||
        (st.mode === 1 && aiStarts() && st.current_turn === "Y");

    if (!isHumanTurn) {
        panel.style.display = "none";
        return;
    }

    panel.style.display = "block";

    // Ne recalcule que si le plateau a changé
    if (st.cursor === _lastHintCursor && _hintData) {
        _renderHint(st);
        return;
    }
    _lastHintCursor = st.cursor;

    const sub = document.getElementById("hintSub");
    if (sub) sub.textContent = "Analyse en cours…";

    try {
        _hintData = await api("/api/hint");
        _renderHint(st);
    } catch (e) {
        if (sub) sub.textContent = "Erreur d'analyse.";
    }
}

function _renderHint(st) {
    if (!_hintData) return;

    const { best_col, scores, min_score, max_score } = _hintData;
    const isRed = st.current_turn === "R";
    const accentColor = isRed ? "#ff6b6b" : "#ffe46b";

    // ── Titre — colonne recommandée ──
    const bestEl = document.getElementById("hintBestCol");
    if (bestEl) {
        bestEl.textContent = best_col !== null ? `⭐ Joue colonne ${best_col + 1}` : "—";
        bestEl.style.color = accentColor;
    }
    const sub = document.getElementById("hintSub");
    if (sub) sub.textContent = "Recommandation MiniMax";

    // ── Barres par colonne ──
    const barsEl = document.getElementById("hintColBars");
    const labelsEl = document.getElementById("hintColLabels");
    if (!barsEl || !labelsEl) return;

    barsEl.innerHTML = "";
    labelsEl.innerHTML = "";

    const range = (max_score - min_score) || 1;

    for (let c = 0; c < scores.length; c++) {
        const sc = scores[c];
        const isBest = c === best_col;

        // Barre
        const bar = document.createElement("div");
        bar.className = "hint-bar";

        if (sc === null) {
            // Colonne pleine
            bar.style.height = "4px";
            bar.style.background = "#1e1e2e";
        } else {
            const h = Math.max(4, Math.round(((sc - min_score) / range) * 50));
            bar.style.height = h + "px";

            if (isBest) {
                bar.style.background = accentColor;
                bar.style.boxShadow = `0 0 10px ${accentColor}99`;
            } else if (sc >= 9000000) {
                // Victoire forcée
                bar.style.background = "rgba(60,210,120,0.9)";
            } else if (sc > 50000) {
                bar.style.background = "rgba(60,210,120,0.65)";
            } else if (sc <= -9000000) {
                // Défaite forcée
                bar.style.background = "rgba(230,80,80,0.9)";
            } else if (sc < -50000) {
                bar.style.background = "rgba(230,80,80,0.50)";
            } else {
                bar.style.background = "rgba(120,150,255,0.45)";
            }
        }
        barsEl.appendChild(bar);

        // Label numéro de colonne
        const lbl = document.createElement("div");
        lbl.className = "hint-col-lbl";
        lbl.textContent = String(c + 1);
        lbl.style.color = isBest ? accentColor : "#555";
        lbl.style.fontWeight = isBest ? "900" : "400";
        labelsEl.appendChild(lbl);
    }
}

// ============================================================
// Helpers
// ============================================================
/**
 * Retourne true si l'IA joue Rouge (elle commence en premier).
 * Couleur IA = "R" → ai_starts = true
 * Couleur IA = "Y" → ai_starts = false (humain commence en rouge)
 */
function aiIsRed() {
    return aiColorEl ? aiColorEl.value === "R" : false;
}

/** Compatibilité avec l'ancien code qui appelle aiStarts() */
function aiStarts() { return aiIsRed(); }

function updateAiStartsVisibility() {
    // Alias pour la compatibilité (loadFileAndSetMode l'appelle)
    updateAiColorVisibility();
}

function updateAiColorVisibility() {
    if (!aiColorGroup) return;
    aiColorGroup.style.display = (modeEl && Number(modeEl.value) === 1) ? "flex" : "none";
}

function updateRobotVisibility() {
    const mode = modeEl ? Number(modeEl.value) : 1;
    const isVsIA = mode === 0;
    if (robotGroup) robotGroup.style.display = isVsIA ? "none" : "flex";
    if (robotRGroup) robotRGroup.style.display = isVsIA ? "flex" : "none";
    if (robotYGroup) robotYGroup.style.display = isVsIA ? "flex" : "none";
}

function updateDepthVisibility() {
    if (!depthGroup) return;
    // Visible seulement pour le robot MiniMax
    // La prédiction a son propre sélecteur indépendant dans son panneau
    const mode = modeEl ? Number(modeEl.value) : 1;
    let needDepth = false;
    if (mode === 0) {
        needDepth = robotAlgoR() === "minimax" || robotAlgoY() === "minimax";
    } else {
        needDepth = robotAlgoValue() === "minimax";
    }
    depthGroup.style.display = needDepth ? "flex" : "none";
}

function robotAlgoValue() {
    if (!robotEl) return "random";
    return robotEl.value;
}

function robotAlgoR() { return robotREl ? robotREl.value : "random"; }

function robotAlgoY() { return robotYEl ? robotYEl.value : "minimax"; }

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
    if (onlinePollingHandle) {
        clearInterval(onlinePollingHandle);
        onlinePollingHandle = null;
    }
}

function startOnlinePolling() {
    stopOnlinePolling();
    if (!onlineMode || !onlineRoomId || !onlinePlayerToken) return;
    onlinePollingHandle = setInterval(async() => {
        if (!onlineMode || !onlineRoomId || !onlinePlayerToken) {
            stopOnlinePolling();
            return;
        }
        try { await refreshOnline(); } catch (e) { console.warn("online polling (ignoré):", e.message); }
    }, 1200);
}

async function joinOnlineMatch() {
    const data = await api("/api/online/join", "POST", {});
    onlineMode = true;
    gameStarted = true; // En ligne : le jeu démarre dès la connexion
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
    if (!onlineRoomId || !onlinePlayerToken) return;
    const newState = await api(
        `/api/online/state?room_id=${encodeURIComponent(onlineRoomId)}&player_token=${encodeURIComponent(onlinePlayerToken)}`
    );
    state = newState;
    if (modeEl) modeEl.value = "3";
    render();
}

async function playOnlineMove(col) {
    if (!onlineRoomId || !onlinePlayerToken) return;
    try {
        await api("/api/online/move", "POST", { room_id: onlineRoomId, player_token: onlinePlayerToken, col });
        await refreshOnline();
    } catch (e) {
        console.error("online move failed:", e.message);
        pushConsoleMessage("Erreur coup en ligne : " + e.message, "danger");
        await refreshOnline().catch(() => {});
    }
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
    const room = onlineRoomId || "?";

    // En attente d'un 2e joueur
    if (waiting) {
        pushConsoleMessageOnce(`waiting|${room}`, "⏳ En attente d'un adversaire...", "warn");
        return;
    }

    // Annoncer la connexion UNE seule fois (indépendant du nb de coups)
    pushConsoleMessageOnce(`found|${room}`, "✅ Adversaire trouvé — partie lancée !", "success");

    // Fin de partie
    if (state.finished) {
        if (state.draw)
            pushConsoleMessageOnce(`end|draw|${room}`, "🤝 Égalité !", "warn");
        else if (state.winner === onlineColor)
            pushConsoleMessageOnce(`end|win|${room}`, "🎉 Bravo, tu as gagné !", "success");
        else
            pushConsoleMessageOnce(`end|lose|${room}`, "Tu as perdu. Bonne chance la prochaine fois.", "danger");
        stopOnlinePolling();
        return;
    }

    // Tour — change à chaque coup (basé sur total)
    if (state.current_turn === onlineColor)
        pushConsoleMessageOnce(`mine|${room}|${total}`, "🟢 C'est à toi de jouer !", "success");
    else
        pushConsoleMessageOnce(`opp|${room}|${total}`, "⏳ Tour de l'adversaire...", "info");
}

function renderWinnerModal() {
    if (!winnerModal || !state) return;
    if (!state.finished) {
        winnerModal.classList.remove("show");
        lastFinishedSignature = null;
        return;
    }
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

    if (state.match_score) {
        setText(scoreR, String(state.match_score.R));
        setText(scoreY, String(state.match_score.Y));
    }

    if (!boardEl) return;

    const winSet = new Set();
    if (state.winning_line) {
        for (const [wr, wc] of state.winning_line) winSet.add(`${wr},${wc}`);
    }

    const lastMove = (state.moves && state.cursor > 0) ? state.moves[state.cursor - 1] : null;

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
            if (winSet.has(`${r},${c}`)) cellDiv.classList.add("winning");
            if (lastMove && lastMove.row === r && lastMove.col === c)
                cellDiv.classList.add("last-move");

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

    // ── Prédiction neuronale automatique ──
    neuralEvalUpdate(state.cursor);
    hintUpdate(state);
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

            if (robotEl) {
                const ra = (state.robot_algo || "").toLowerCase();
                if (ra === "neural") robotEl.value = "neural";
                else if (ra === "minimax") robotEl.value = "minimax";
                else robotEl.value = "random";
            }
            if (robotREl && state.robot_algo_r) {
                const ra = state.robot_algo_r.toLowerCase();
                robotREl.value = ra === "neural" ? "neural" : ra === "minimax" ? "minimax" : "random";
            }
            if (robotYEl && state.robot_algo_y) {
                const ra = state.robot_algo_y.toLowerCase();
                robotYEl.value = ra === "neural" ? "neural" : ra === "minimax" ? "minimax" : "random";
            }
            if (depthEl) depthEl.value = String(state.robot_depth);
            // Synchroniser la couleur IA depuis l'état serveur
            if (aiColorEl && state.ai_starts !== undefined)
                aiColorEl.value = state.ai_starts ? "R" : "Y";

            updateAiColorVisibility();
            updateRobotVisibility();
            updateDepthVisibility();
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
        if (onlineMode) { await playOnlineMove(col); return; } // online: pas besoin de gameStarted
        if (!gameStarted) return;
        if (!state || state.finished || state.paused) return;
        if (moveInFlight) return;

        const isHumanTurn =
            state.mode === 2 ||
            (state.mode === 1 && !aiStarts() && state.current_turn === "R") ||
            (state.mode === 1 && aiStarts() && state.current_turn === "Y");

        if (!isHumanTurn) return;

        // Affichage optimiste AVANT le await
        if (state.board && state.board[0][col] === ".") {
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

        moveInFlight = true;
        await api("/api/move", "POST", { col });
        await refresh();
        await maybeAutoplay();
    } catch (e) {
        console.log(e.message);
        await refresh();
    } finally {
        moveInFlight = false;
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
    if (!gameStarted) return;
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
// AI THINKING BAR
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
    gameStarted = false;
    onlineMode = false;
    onlineRoomId = null;
    onlinePlayerToken = null;
    onlineColor = null;
    stopOnlinePolling();
    lastConsoleSignature = null;
    lastFinishedSignature = null;
    clearConsole();
    pushConsoleMessage("Plateau réinitialisé. Appuie sur ▶ Start pour commencer.", "info");
    await api("/api/new", "POST");
    hoveredCol = null;
    // Reset indicateurs
    _lastHintCursor = -2;
    _hintData = null;
    _lastNeuralCursor = -1;
    await refresh();
});

on(btnStart, "click", async() => {
    if (onlineMode) {
        // En ligne : Start relance le polling si besoin
        if (onlineRoomId && onlinePlayerToken) startOnlinePolling();
        return;
    }
    gameStarted = true;
    clearConsole();
    pushConsoleMessage("Partie lancée !", "success");
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
    updateAiColorVisibility();
    updateRobotVisibility();
    updateDepthVisibility();

    if (mode === 3) {
        stopAutoplay();
        try { await joinOnlineMatch(); } catch (e) {
            onlineMode = false;
            stopOnlinePolling();
            pushConsoleMessage("Impossible de lancer le mode en ligne : " + e.message, "danger");
            if (modeEl) modeEl.value = "1";
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

// Couleur IA change (remplace "IA commence")
on(aiColorEl, "change", async() => {
    if (onlineMode) return;
    stopAutoplay();
    lastFinishedSignature = null;
    _lastHintCursor = -2;
    _hintData = null;
    // Rouge = IA commence (ai_starts:true), Jaune = IA joue 2e (ai_starts:false)
    const isRed = aiColorEl.value === "R";
    await api("/api/set", "POST", { ai_starts: isRed });
    await api("/api/new", "POST");
    hoveredCol = null;
    clearConsole();
    pushConsoleMessage(
        isRed ?
        "IA joue 🔴 Rouge — elle commence en premier." :
        "IA joue 🟡 Jaune — tu commences en premier (Rouge).",
        "info"
    );
    await refresh();
    await maybeAutoplay();
});

// Changement de robot (mode 1)
on(robotEl, "change", async() => {
    if (onlineMode) return;
    stopAutoplay();
    updateDepthVisibility();
    await api("/api/set", "POST", { robot_algo: robotAlgoValue() });
    await refresh();
    await maybeAutoplay();
});

// Changement Robot Rouge (mode 0)
on(robotREl, "change", async() => {
    if (onlineMode) return;
    stopAutoplay();
    updateDepthVisibility();
    await api("/api/set", "POST", { robot_algo_r: robotAlgoR() });
    await refresh();
    await maybeAutoplay();
});

// Changement Robot Jaune (mode 0)
on(robotYEl, "change", async() => {
    if (onlineMode) return;
    stopAutoplay();
    updateDepthVisibility();
    await api("/api/set", "POST", { robot_algo_y: robotAlgoY() });
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


// Parties précédentes (DB)
// ── HISTORY MODAL ─────────────────────────────────────────
let _allGames = [];

// ── helpers récupérés à chaque appel (jamais null) ──────────
function _hEl(id) { return document.getElementById(id); }

function _statusBadge(status) {
    const s = (status || "").toLowerCase();
    if (s.includes("win") || s.includes("gagn") || s === "finished")
        return `<span class="history-status-badge win">${status}</span>`;
    if (s.includes("draw") || s.includes("egal") || s === "draw")
        return `<span class="history-status-badge draw">${status}</span>`;
    if (s === "in_progress" || s === "en cours" || s === "live")
        return `<span class="history-status-badge live">En cours</span>`;
    return `<span class="history-status-badge">${status || "?"}</span>`;
}

function _renderHistoryList(games) {
    const listEl = _hEl("historyList");
    const countEl = _hEl("historyCount");
    if (!listEl) return;
    if (!games.length) {
        listEl.innerHTML = '<div class="history-empty">Aucune partie trouvée.</div>';
        if (countEl) countEl.textContent = "";
        return;
    }
    if (countEl) countEl.textContent = `${games.length} partie(s)`;
    listEl.innerHTML = games.map(g => {
                const seq = (g.original_sequence || "").slice(0, 45);
                const src = g.source_filename || "";
                const rows = g.rows || 9,
                    cols = g.cols || 9;
                const nbMoves = seq ? seq.split(",").filter(Boolean).length : 0;
                const winner = g.winner ? (g.winner === "R" ? "🔴 Rouge" : "🟡 Jaune") : (g.draw ? "🤝 Égalité" : "");
                return `<div class="history-item">
            <div class="history-item-id">${g.id}<span>ID</span></div>
            <div class="history-item-main">
                <div class="history-item-top">
                    <span class="history-item-title">Partie #${g.id}</span>
                    ${_statusBadge(g.status)}
                    ${winner ? `<span style="font-size:12px;color:#b8c7ee;">${winner}</span>` : ""}
                </div>
                <div class="history-item-meta">
                    <span>📐 ${rows}×${cols}</span>
                    ${nbMoves ? `<span>🎯 ${nbMoves} coups</span>` : ""}
                    ${src ? `<span>📂 ${src.slice(0, 20)}</span>` : ""}
                </div>
                ${seq ? `<div class="history-item-seq">${seq}${(g.original_sequence||"").length > 45 ? "…" : ""}</div>` : ""}
            </div>
            <button class="history-load-btn" onclick="_loadGame(${g.id}, this)">▶ Charger</button>
        </div>`;
    }).join("");
}

async function _loadGame(gid, btn) {
    const modal = _hEl("historyModal");
    if (btn) { btn.disabled = true; btn.textContent = "\u23f3\u2026"; }
    try {
        stopAutoplay();
        onlineMode = false; onlineRoomId = null; onlinePlayerToken = null; onlineColor = null;
        stopOnlinePolling(); lastConsoleSignature = null;
        lastFinishedSignature = null;  // reset avant refresh
        clearConsole();
        await api(`/api/db/load/${gid}`, "POST");
        if (modal) modal.style.display = "none";   // fermer la modal
        await refresh();
        // Partie terminee : bloquer la popup winner mais garder les pions eclaires
        if (state && state.finished) {
            lastFinishedSignature = `${state.game_index}|${state.winner}|${state.draw}|${state.total}`;
            if (winnerModal) removeClass(winnerModal, "show");
        }
        const nb = state && state.total ? state.total + " coups" : "";
        pushConsoleMessage(`Partie #${gid} chargee (${nb}).`, "success");
    } catch (e) {
        if (btn) { btn.disabled = false; btn.textContent = "\u25b6 Charger"; }
        pushConsoleMessage("Erreur chargement : " + e.message, "danger");
    }
}

function _openHistoryModal() {
    const modal   = _hEl("historyModal");
    const listEl  = _hEl("historyList");
    const searchEl= _hEl("historySearch");
    if (!modal) { console.warn("historyModal not found in DOM"); return false; }
    if (listEl)  listEl.innerHTML  = '<div class="history-empty">⏳ Chargement…</div>';
    if (searchEl) searchEl.value   = "";
    // style.display direct — écrase le display:none inline du HTML
    modal.style.display = "flex";
    return true;
}

function _closeHistoryModal() {
    const modal = _hEl("historyModal");
    if (modal) modal.style.display = "none";
}

// ── Wiring — appliqué après DOMContentLoaded si nécessaire ──
function _wireHistoryModal() {
    const closeBtn = _hEl("btnCloseHistory");
    const modal    = _hEl("historyModal");
    const searchEl = _hEl("historySearch");
    if (closeBtn && !closeBtn._wired) {
        closeBtn.addEventListener("click", _closeHistoryModal);
        closeBtn._wired = true;
    }
    if (modal && !modal._wiredBg) {
        modal.addEventListener("click", (e) => { if (e.target === modal) _closeHistoryModal(); });
        modal._wiredBg = true;
    }
    if (searchEl && !searchEl._wired) {
        searchEl.addEventListener("input", () => {
            const q = (searchEl.value || "").toLowerCase().trim();
            _renderHistoryList(q ? _allGames.filter(g =>
                String(g.id).includes(q) ||
                (g.status || "").toLowerCase().includes(q) ||
                (g.original_sequence || "").toLowerCase().includes(q) ||
                (g.source_filename || "").toLowerCase().includes(q)
            ) : _allGames);
        });
        searchEl._wired = true;
    }
}
_wireHistoryModal();

// ── Bouton "Parties précédentes" ────────────────────────────
on(btnLoadDb, "click", async() => {
    _wireHistoryModal();   // re-wire au cas où le DOM n'était pas prêt
    if (!_openHistoryModal()) return;
    try {
        const data = await api("/api/db/list");
        _allGames  = (data.games || []).sort((a, b) => b.id - a.id);
        _renderHistoryList(_allGames);
    } catch (e) {
        const listEl = _hEl("historyList");
        if (listEl) listEl.innerHTML =
            `<div class="history-empty" style="color:#ff7070;">
               ⚠️ ${e.message}<br><small>Vérifie que la DB est disponible.</small>
             </div>`;
    }
});

// Bouton Paramètres supprimé

// Modales winner
on(btnCloseWinner, "click", () => { removeClass(winnerModal, "show"); });
on(btnNewFromWinner, "click", async() => {
    removeClass(winnerModal, "show");
    if (onlineMode) { pushConsoleMessage("Pour rejouer en ligne, relance le mode En ligne.", "warn"); return; }
    stopAutoplay();
    gameStarted = false;
    lastFinishedSignature = null;
    await api("/api/new", "POST");
    hoveredCol = null;
    _lastHintCursor = -2;
    _hintData = null;
    _lastNeuralCursor = -1;
    clearConsole();
    pushConsoleMessage("Plateau réinitialisé. Appuie sur ▶ Start pour commencer.", "info");
    await refresh();
});

// ============================================================
// PREDICTION — bouton 🔮 Prédire (MiniMax)
// ============================================================
const predictPanel = document.getElementById("predictPanel");
const predictLoading = document.getElementById("predictLoading");
const predictResult = document.getElementById("predictResult");
const predictWinner = document.getElementById("predictWinner");
const predictDetail = document.getElementById("predictDetail");
const predictFill = document.getElementById("predictFill");
const predictPct = document.getElementById("predictPct");

// ── Prédiction — clic sur 🔮 Prédire ───────────────────────
on(btnPredict, "click", async() => {
    if (!predictPanel) return;
    predictPanel.style.display = "block";
    if (predictLoading) predictLoading.style.display = "flex";
    if (predictResult)  predictResult.style.display  = "none";

    try {
        const data = await api("/api/predict");

        if (predictLoading) predictLoading.style.display = "none";
        if (predictResult)  predictResult.style.display  = "block";

        const isR      = data.winner === "R";
        const isY      = data.winner === "Y";
        const isDraw   = data.winner === "draw";
        const colorName= isR ? "Rouge 🔴" : isY ? "Jaune 🟡" : null;
        const certain  = !!data.certain;
        const ml       = data.moves_left;
        const threat   = data.threat || null;

        // ── Titre ──────────────────────────────────────────────
        if (colorName && certain) {
            predictWinner.textContent = colorName + " va gagner";
            predictWinner.style.color = isR ? "#ff6b6b" : "#ffe46b";
        } else if (colorName && !certain) {
            predictWinner.textContent = colorName + " en avantage";
            predictWinner.style.color = isR ? "#ff9966" : "#ffe49a";
        } else if (isDraw) {
            predictWinner.textContent = "🤝 Égalité probable";
            predictWinner.style.color = "#b8c7ee";
        } else {
            predictWinner.textContent = "🔮 Position équilibrée";
            predictWinner.style.color = "#b8c7ee";
        }

        // ── Variables utiles ────────────────────────────────────
        const bestCol     = (data.best_col != null) ? data.best_col + 1 : null;
        const currentMove = data.current_move || "?";
        const turns       = ml > 0 ? Math.max(1, Math.ceil(ml / 2)) : null;
        const winColor    = isR ? "#ff7070" : "#ffe46b";

        // ── Clé de la victoire — SEULEMENT si victoire prouvée (certain) ──
        let keyHtml = "";
        if (bestCol && certain && ml > 0 && !data.finished) {
            keyHtml = `
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;
                        padding:10px 14px;border-radius:11px;
                        background:rgba(255,255,255,.05);
                        border:1px solid rgba(255,255,255,.10);">
                <div style="text-align:center;min-width:50px;flex-shrink:0;">
                    <div style="font-size:28px;font-weight:900;color:${winColor};line-height:1;">${bestCol}</div>
                    <div style="font-size:9px;font-weight:800;letter-spacing:.8px;color:#7a92c0;margin-top:2px;">COLONNE</div>
                </div>
                <div style="border-left:1px solid rgba(255,255,255,.08);padding-left:12px;flex:1;">
                    <div style="font-size:10px;font-weight:800;letter-spacing:.8px;color:#7a92c0;">🔑 CLÉ DE LA VICTOIRE</div>
                    <div style="font-size:13px;font-weight:800;color:${winColor};margin-top:3px;">
                        Jouer col&nbsp;${bestCol} maintenant
                    </div>
                    <div style="font-size:12px;color:#b8c7ee;margin-top:2px;">
                        ${certain ? `Victoire en <strong>${ml}</strong> coup(s) — ${turns} tour(s)` :
                                    `Victoire estimée ~<strong>${ml}</strong> coup(s) — ~${turns} tour(s)`}
                    </div>
                </div>
            </div>`;
        }

        // ── Lignes de détail ─────────────────────────────────────
        let lines = [];
        if (threat === "fork") {
            lines.push(`🔱 <strong>Fork</strong> — 2 menaces créées, victoire forcée en 3 coups.`);
        } else if (threat === "double") {
            lines.push(`💀 <strong>Double menace</strong> — défaite inévitable en 2 coups.`);
        } else if (threat === "single") {
            lines.push(`⚡ Menace à bloquer immédiatement.`);
        }
        if (data.finished) {
            lines.push("La partie est terminée.");
        } else if (certain && ml > 0) {
            lines.push(`✅ <strong>Suite prouvée</strong> — ${COLOR_NAME_JS(data.winner)} gagne en <strong>${ml} coup(s)</strong> (~${turns} tour(s)).`);
        } else if (!certain && colorName && ml > 0) {
            lines.push(`📊 Victoire estimée ~<strong>${ml} coup(s)</strong> (~${turns} tour(s)).`);
        } else if (!certain && colorName) {
            lines.push(`📊 Avantage ${colorName.split(" ")[0]} positionnel.`);
        } else if (isDraw) {
            lines.push("Position équilibrée — aucun avantage décisif.");
        } else {
            lines.push(data.explanation || "Position équilibrée.");
        }

        if (predictDetail) predictDetail.innerHTML = keyHtml + lines.join("<br>");

        // ── Barre d'avantage ───────────────────────────────────
        let pct = data.score_pct !== undefined ? data.score_pct : 50;
        pct = Math.max(5, Math.min(95, pct));

        if (predictFill) {
            predictFill.style.width = pct + "%";
            predictFill.style.background =
                pct > 55 ? "linear-gradient(90deg,#e53935,#b21a1a)" :
                pct < 45 ? "linear-gradient(90deg,#b58a00,#ffe46b)" :
                           "linear-gradient(90deg,#378ADD,#1a4fa0)";
        }
        if (predictPct) predictPct.textContent =
            pct > 55 ? `Rouge ${pct}%` :
            pct < 45 ? `Jaune ${100 - pct}%` :
                       `Équilibré 50/50`;

    } catch (e) {
        if (predictLoading) predictLoading.style.display = "none";
        if (predictResult)  predictResult.style.display  = "block";
        if (predictWinner) {
            predictWinner.textContent = "⚠️ Erreur";
            predictWinner.style.color = "#ff6b6b";
        }
        if (predictDetail) predictDetail.innerHTML = e.message || "Erreur inconnue.";
    }
});
function COLOR_NAME_JS(c) { return c === "R" ? "Rouge 🔴" : "Jaune 🟡"; }

on(btnClosePrediction, "click", () => {
    if (predictPanel) predictPanel.style.display = "none";
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
on(btnPaintClear, "click", () => {
    if (!state) return;
    buildPaintBoard(state.rows, state.cols);
});
on(btnPaintCancel, "click", () => { if (paintModal) paintModal.classList.remove("show"); });
on(btnPaintApply, "click", async() => {
    if (!paintGrid) return;
    try {
        const data = await api("/api/paint", "POST", { board: paintGrid });
        if (paintModal) paintModal.classList.remove("show");
        hoveredCol = null;
        // Forcer la mise à jour des indicateurs même si cursor reste à 0
        _lastNeuralCursor = -1;
        _lastHintCursor = -2;
        _hintData = null;
        if (data.paint_analysis) {
            const turn = data.paint_analysis.current_turn_inferred === "R" ? "Rouge" : "Jaune";
            pushConsoleMessage(`Position chargée — C'est au joueur ${turn} de jouer.`, "success");
        }
        await refresh();
        await maybeAutoplay();
    } catch (e) { alert("Erreur paint : " + e.message); }
});

// ============================================================
// IMPORT FICHIER LOCAL .TXT
// ============================================================

/** Données parsées du dernier fichier sélectionné */
let _parsedFileData = null;

/**
 * Extrait la séquence depuis le NOM du fichier.
 * Ex: "31313.txt"        → "31313"
 *     "352735271153.txt" → "352735271153"
 * Ne garde que les chiffres 1-9 (colonnes 1-indexées).
 * Retourne { sequence } ou null si aucun chiffre 1-9 trouvé.
 */
function parseGameFileName(filename) {
    // Retirer l'extension (.txt, .csv, etc.)
    var name = filename;
    var dotIdx = filename.lastIndexOf(".");
    if (dotIdx > 0) {
        name = filename.substring(0, dotIdx);
    }

    // Garder uniquement les chiffres 1-9
    var digits = "";
    for (var i = 0; i < name.length; i++) {
        var c = name[i];
        if (c >= "1" && c <= "9") {
            digits += c;
        }
    }

    if (digits.length === 0) return null;
    return { sequence: digits };
}

// ── Sélection du fichier ──
on(fileInput, "change", function() {
    _parsedFileData = null;
    if (fileImportOptions) fileImportOptions.style.display = "none";
    if (btnImportFile) btnImportFile.disabled = true;

    if (!fileInput || !fileInput.files || !fileInput.files[0]) {
        if (fileInputName) fileInputName.textContent = "Choisir un fichier .txt…";
        return;
    }
    var file = fileInput.files[0];
    if (fileInputName) fileInputName.textContent = file.name;

    // La séquence EST le nom du fichier (ex: 31313.txt → séquence "31313")
    var parsed = parseGameFileName(file.name);
    if (!parsed) {
        alert(
            "Nom de fichier invalide : \"" + file.name + "\"\n\n" +
            "Le nom du fichier doit être une suite de chiffres 1-9.\n" +
            "Exemple : 31313.txt  ou  352735271153.txt"
        );
        fileInput.value = "";
        if (fileInputName) fileInputName.textContent = "Choisir un fichier .txt…";
        return;
    }

    _parsedFileData = parsed;
    if (btnImportFile) btnImportFile.disabled = false;
    pushConsoleMessage(
        "📂 \"" + file.name + "\" — " + parsed.sequence.length + " coups. Clique sur ▶ Charger la partie.",
        "info"
    );
});

// ── Drag & drop sur le label ──
on(fileInputLabel, "dragover", function(e) {
    e.preventDefault();
    if (fileInputLabel) fileInputLabel.style.background = "rgba(55,138,221,.1)";
});
on(fileInputLabel, "dragleave", function() {
    if (fileInputLabel) fileInputLabel.style.background = "";
});
on(fileInputLabel, "drop", function(e) {
    e.preventDefault();
    if (fileInputLabel) fileInputLabel.style.background = "";
    if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files[0]) return;
    var file = e.dataTransfer.files[0];
    if (fileInput) {
        try {
            var dt = new DataTransfer();
            dt.items.add(file);
            fileInput.files = dt.files;
        } catch (err) {}
        fileInput.dispatchEvent(new Event("change"));
    }
});

/** Charge la séquence sur le serveur puis applique le mode demandé */
async function loadFileAndSetMode(targetMode) {
    if (!_parsedFileData) { alert("Aucun fichier chargé."); return; }
    try {
        stopAutoplay();
        onlineMode = false;
        onlineRoomId = null;
        onlinePlayerToken = null;
        onlineColor = null;
        stopOnlinePolling();
        lastConsoleSignature = null;
        lastFinishedSignature = null;
        clearConsole();

        var sequence = _parsedFileData.sequence;
        var fileName = (fileInput && fileInput.files && fileInput.files[0]) ? fileInput.files[0].name : "fichier";

        pushConsoleMessage("⏳ Chargement de \"" + fileName + "\"…", "info");

        // La séquence vient du nom de fichier → toujours 1-indexée (chiffres 1-9)
        // On passe rows/cols null → le serveur utilise la config courante
        await api("/api/load_sequence", "POST", {
            sequence: sequence,
            rows: null,
            cols: null,
            starting_color: "R"
        });

        if (modeEl) modeEl.value = String(targetMode);
        await api("/api/set", "POST", { mode: targetMode });

        hoveredCol = null;
        // Reset indicateurs pour forcer la mise à jour après import
        _lastNeuralCursor = -1;
        _lastHintCursor = -2;
        _hintData = null;
        gameStarted = false;
        updateAiStartsVisibility();
        updateRobotVisibility();
        updateDepthVisibility();

        if (fileImportOptions) fileImportOptions.style.display = "none";
        await refresh();

        var nb = (state && state.cursor) ? state.cursor : 0;
        pushConsoleMessage("✅ " + nb + " coups rejoués depuis \"" + fileName + "\".", "success");
        pushConsoleMessage("Appuie sur ▶ Start pour continuer.", "info");

    } catch (e) {
        alert("Erreur lors du chargement :\n" + e.message);
    }
}

// ── Bouton "Charger la partie" → charge immédiatement avec le mode actuel ──
on(btnImportFile, "click", function() {
    if (!_parsedFileData) { pushConsoleMessage("Aucun fichier sélectionné.", "warn"); return; }
    // Utiliser le mode actuellement sélectionné dans la toolbar
    var currentMode = modeEl ? Number(modeEl.value) : 2;
    // Si mode En ligne, charger en Joueur vs Joueur par défaut
    if (currentMode === 3) currentMode = 2;
    loadFileAndSetMode(currentMode);
});

// Garder les anciens boutons actifs au cas où fileImportOptions est affiché
on(btnFileContinueIAvIA, "click", function() { loadFileAndSetMode(0); });
on(btnFileContinueJvsIA, "click", function() { loadFileAndSetMode(1); });
on(btnFileContinueJvsJ,  "click", function() { loadFileAndSetMode(2); });

// ============================================================
// BOOT
// ============================================================
if (onlineConsoleEl) {
    clearConsole();
    pushConsoleMessage("Bienvenue sur Puissance 4.", "info");
}
updateAiColorVisibility();
updateRobotVisibility();
updateDepthVisibility();
refresh(); // pas de maybeAutoplay au boot — attendre ▶ Start
