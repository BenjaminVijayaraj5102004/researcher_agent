/* ═══════════════════════════════════════════════════════════════════════════
   Researcher AI — Frontend (Vercel deployment)
   API calls use relative paths so they work on any domain automatically
   ═══════════════════════════════════════════════════════════════════════════ */

// On Vercel, frontend and API share the same origin — use relative paths
const API_BASE = "";

let currentMode = "stream";
let currentResearchId = null;
let currentResult = null;
let eventSource = null;

// ── Init ─────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    checkHealth();
    setupInputListeners();
    setTimeout(loadHistory, 1200);
});

async function checkHealth() {
    try {
        const res = await fetch(`${API_BASE}/api/health`, { signal: AbortSignal.timeout(6000) });
        const data = await res.json();
        updateStatusBadge("active", "System Ready");
        if (!data.services?.groq)   showToast("⚠️ Groq API key not configured", "error");
        if (!data.services?.serper) showToast("⚠️ Serper API key not configured", "error");
    } catch (e) {
        updateStatusBadge("error", "Backend Offline");
        showToast("❌ Backend not reachable. Check environment variables.", "error");
    }
}

function setupInputListeners() {
    const topicInput = document.getElementById("topicInput");
    topicInput.addEventListener("keypress", (e) => { if (e.key === "Enter") startResearch(); });
    topicInput.addEventListener("input", () => {
        document.getElementById("submitBtn").disabled = topicInput.value.trim().length < 3;
    });
}

// ── Navigation ────────────────────────────────────────────────────────────────

function showSection(name) {
    document.querySelectorAll(".section").forEach(s => s.classList.remove("active"));
    const s = document.getElementById(`section-${name}`);
    if (s) s.classList.add("active");
    if (name === "history") loadHistory();
}

// ── Controls ─────────────────────────────────────────────────────────────────

function adjustSources(delta) {
    const input = document.getElementById("sourcesInput");
    input.value = Math.min(10, Math.max(1, parseInt(input.value || 5) + delta));
}

function setMode(mode) {
    currentMode = mode;
    document.querySelectorAll(".mode-btn").forEach(b => {
        b.classList.toggle("active", b.dataset.mode === mode);
    });
}

// ── Research Pipeline ────────────────────────────────────────────────────────

async function startResearch() {
    const topic = document.getElementById("topicInput").value.trim();
    if (!topic || topic.length < 3) {
        showToast("Please enter a topic (min 3 characters)", "error");
        return;
    }
    const context     = document.getElementById("contextInput").value.trim();
    const maxSources  = parseInt(document.getElementById("sourcesInput").value || 5);

    hideResult();
    showProgress();
    resetAgentCards();
    clearLogs();

    const btn = document.getElementById("submitBtn");
    btn.disabled = true;
    btn.querySelector(".btn-text").textContent = "Generating...";
    setProgressMeta(`Topic: "${topic}"`);
    addLog("🚀 Research pipeline initiated");

    try {
        if (currentMode === "stream") {
            await runStreamingResearch({ topic, additional_context: context || null, max_sources: maxSources });
        } else {
            await runSyncResearch({ topic, additional_context: context || null, max_sources: maxSources });
        }
    } catch (e) {
        addLog(`❌ Error: ${e.message}`);
        showToast(`Research failed: ${e.message}`, "error");
        updateStatusBadge("active", "System Ready");
    }

    btn.disabled = false;
    btn.querySelector(".btn-text").textContent = "Generate Research Paper";
}

async function runStreamingResearch(payload) {
    const startRes = await fetch(`${API_BASE}/api/research/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });
    if (!startRes.ok) {
        const err = await startRes.json();
        throw new Error(err.detail || "Failed to start research");
    }
    const { research_id, stream_url } = await startRes.json();
    currentResearchId = research_id;
    addLog(`📋 Research ID: ${research_id.slice(0, 8)}...`);

    return new Promise((resolve, reject) => {
        if (eventSource) eventSource.close();
        eventSource = new EventSource(`${API_BASE}${stream_url}`);
        updateStatusBadge("active", "Processing...");

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === "done") {
                    eventSource.close();
                    fetchAndDisplayResult(research_id);
                    resolve();
                    return;
                }
                if (data.type === "error") {
                    eventSource.close();
                    reject(new Error(data.message));
                    return;
                }
                handleProgressUpdate(data);
                if (data.status === "completed" || data.status === "failed") {
                    eventSource.close();
                    if (data.status === "completed") setTimeout(() => fetchAndDisplayResult(research_id), 600);
                    resolve();
                }
            } catch (e) { console.error("SSE parse error:", e); }
        };

        eventSource.onerror = () => {
            eventSource.close();
            setTimeout(() => fetchAndDisplayResult(currentResearchId), 1000);
            resolve();
        };

        setTimeout(() => {
            if (eventSource) { eventSource.close(); reject(new Error("Research timed out after 5 minutes")); }
        }, 5 * 60 * 1000);
    });
}

async function runSyncResearch(payload) {
    addLog("⏳ Running synchronous research (1–3 minutes)...");
    updateProgress(10, "Sending to backend...");
    const res = await fetch(`${API_BASE}/api/research/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Research generation failed");
    }
    const result = await res.json();
    currentResult = result;
    currentResearchId = result.research_id;
    updateProgress(100, "✅ Complete!");
    displayResult(result);
}

async function fetchAndDisplayResult(research_id) {
    try {
        const res = await fetch(`${API_BASE}/api/research/result/${research_id}`);
        if (!res.ok) {
            await new Promise(r => setTimeout(r, 2000));
            const res2 = await fetch(`${API_BASE}/api/research/result/${research_id}`);
            if (!res2.ok) throw new Error("Result not available");
            const data2 = await res2.json();
            currentResult = data2;
            displayResult(data2);
            return;
        }
        const data = await res.json();
        currentResult = data;
        displayResult(data);
    } catch (e) {
        addLog(`⚠️ Could not fetch result: ${e.message}`);
    }
}

// ── Progress Handlers ─────────────────────────────────────────────────────────

function handleProgressUpdate(data) {
    const { status, current_step, progress_percentage, message, logs } = data;
    updateProgress(progress_percentage || 0, message || current_step);
    setProgressMeta(current_step || "");
    if (logs && logs.length > 0) addLog(logs[logs.length - 1]);

    if (status === "pending") {
        setAgentActive("main", "active");
        setAgentStep("step-main", "active");
    } else if (status === "fetching") {
        setAgentActive("main", "done");
        setAgentActive("fetch", "active");
        setAgentStep("step-fetch", "active");
    } else if (status === "writing") {
        setAgentActive("fetch", "done");
        setAgentActive("writer", "active");
        setAgentStep("step-writer", "active");
    } else if (status === "reviewing") {
        setAgentActive("writer", "done");
        setAgentActive("review", "active");
        setAgentStep("step-review", "active");
    } else if (status === "completed") {
        ["main","fetch","writer","review"].forEach(k => setAgentActive(k, "done"));
        ["step-main","step-fetch","step-writer","step-review"].forEach(id => setAgentStep(id, "done"));
        updateStatusBadge("active", "Complete ✅");
        showToast("🎉 Research paper generated successfully!", "success");
    } else if (status === "failed") {
        updateStatusBadge("error", "Failed");
        showToast("❌ Research failed", "error");
    }
}

function updateProgress(pct, message) {
    document.getElementById("progressBar").style.width = `${pct}%`;
    document.getElementById("progressPct").textContent = `${pct}%`;
    if (message) setProgressMeta(message);
}

function setProgressMeta(text) {
    document.getElementById("progressMeta").textContent = text;
}

function setAgentActive(key, state) {
    const card = document.getElementById(`agentCard-${key}`);
    if (!card) return;
    card.classList.remove("active", "done");
    if (state) card.classList.add(state);
    const st = card.querySelector(".agent-card-status");
    if (st) st.textContent = { active: "Running...", done: "Complete ✅", "": "Waiting" }[state] || "Waiting";
}

function setAgentStep(stepId, state) {
    const el = document.getElementById(stepId);
    if (!el) return;
    el.classList.remove("active", "done");
    if (state) el.classList.add(state);
}

// ── Logs ──────────────────────────────────────────────────────────────────────

function addLog(message) {
    const logBody = document.getElementById("logBody");
    if (!logBody) return;
    const entry = document.createElement("div");
    entry.className = "log-entry";
    const ts = new Date().toLocaleTimeString("en-US", { hour12: false });
    entry.innerHTML = `<span class="log-ts">[${ts}]</span>${escapeHtml(message)}`;
    logBody.appendChild(entry);
    logBody.scrollTop = logBody.scrollHeight;
    while (logBody.children.length > 50) logBody.removeChild(logBody.firstChild);
}

function clearLogs() {
    const lb = document.getElementById("logBody");
    if (lb) lb.innerHTML = "";
}

// ── Result Display ────────────────────────────────────────────────────────────

function displayResult(result) {
    if (!result || result.status === "failed") {
        showToast("Research failed. Check logs for details.", "error");
        return;
    }
    hideProgress();
    showResult();
    renderMetrics(result);

    document.getElementById("paperDisplay").textContent =
        result.final_paper || result.writer_output?.full_paper || "No paper content.";

    renderSources(result.fetch_output);
    renderReview(result.review_output);
    showTab("paper");
    updateStatusBadge("active", "System Ready");
}

function renderMetrics(result) {
    const metrics = [];
    if (result.fetch_output) {
        metrics.push({ value: result.fetch_output.total_sources || 0, label: "Sources" });
        metrics.push({ value: result.fetch_output.key_facts?.length || 0, label: "Key Facts" });
    }
    if (result.writer_output) {
        metrics.push({ value: result.writer_output.word_count || 0, label: "Words" });
        metrics.push({ value: result.writer_output.sections?.length || 0, label: "Sections" });
    }
    if (result.review_output) {
        metrics.push({ value: `${result.review_output.quality_score?.toFixed(1)}/10`, label: "Quality" });
    }
    document.getElementById("metricsRow").innerHTML = metrics.map(m =>
        `<div class="metric-card"><div class="metric-value">${m.value}</div><div class="metric-label">${m.label}</div></div>`
    ).join("");
}

function renderSources(fetchOutput) {
    const el = document.getElementById("sourcesList");
    if (!fetchOutput?.search_results?.length) {
        el.innerHTML = '<p style="color:var(--text-muted);font-size:.875rem;">No source data available.</p>';
        return;
    }
    el.innerHTML = fetchOutput.search_results.map((r, i) => `
        <div class="source-item">
            <span class="source-index">[${i + 1}]</span>
            <div class="source-info">
                <div class="source-title">${escapeHtml(r.title)}</div>
                <a href="${escapeHtml(r.url)}" target="_blank" rel="noopener" class="source-url">${escapeHtml(r.url)}</a>
                <div class="source-snippet">${escapeHtml(r.snippet)}</div>
            </div>
        </div>`).join("");
}

function renderReview(reviewOutput) {
    const el = document.getElementById("reviewDisplay");
    if (!reviewOutput) {
        el.innerHTML = '<p style="color:var(--text-muted);font-size:.875rem;">No review data available.</p>';
        return;
    }
    const qPct  = (reviewOutput.quality_score / 10) * 100;
    const plag  = reviewOutput.plagiarism_check?.score || 0;
    const issues = reviewOutput.alignment_issues || [];
    const imps   = reviewOutput.improvements_made || [];

    el.innerHTML = `
        <div class="review-metric">
            <h4>📊 Quality Score</h4>
            <div style="display:flex;align-items:center;gap:1rem;margin-bottom:.5rem;">
                <div class="score-bar" style="flex:1"><div class="score-fill" style="width:${qPct}%"></div></div>
                <span style="font-family:var(--font-mono);font-weight:700;color:var(--lavender)">${reviewOutput.quality_score?.toFixed(1)}/10</span>
            </div>
            <p style="font-size:.8rem;color:var(--text-muted)">IEEE compliance: ${reviewOutput.ieee_compliance ? "✅ Passed" : "⚠️ Issues found"}</p>
        </div>
        <div class="review-metric">
            <h4>🔍 Originality Check</h4>
            <div style="display:flex;align-items:center;gap:1rem;margin-bottom:.5rem;">
                <div class="score-bar" style="flex:1"><div class="score-fill" style="width:${100 - plag}%;background:linear-gradient(90deg,#4ade80,#22c55e)"></div></div>
                <span style="font-family:var(--font-mono);font-weight:700;color:#4ade80">${(100 - plag).toFixed(0)}% Original</span>
            </div>
            <p style="font-size:.8rem;color:var(--text-muted)">${reviewOutput.plagiarism_check?.is_original ? "✅ Paper appears original" : "⚠️ Some sections may need rewriting"}</p>
        </div>
        ${issues.length ? `<div class="review-metric"><h4>⚠️ Alignment Issues (${issues.length})</h4>${issues.map(i =>
            `<div class="issue-item"><span class="issue-label">[${escapeHtml(i.section)}]</span> ${escapeHtml(i.issue)}<div style="font-size:.75rem;color:var(--lavender);margin-top:.25rem">→ ${escapeHtml(i.suggestion)}</div></div>`
        ).join("")}</div>` : ""}
        ${imps.length ? `<div class="review-metric"><h4>✅ Improvements (${imps.length})</h4>${imps.map(i =>
            `<div class="issue-item">✓ ${escapeHtml(i)}</div>`
        ).join("")}</div>` : ""}`;
}

// ── Tabs ──────────────────────────────────────────────────────────────────────

function showTab(name) {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("active", b.id === `tab-${name}`));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.toggle("active", c.id === `tabContent-${name}`));
}

// ── Panel Visibility ──────────────────────────────────────────────────────────

function showProgress() { document.getElementById("progressPanel").classList.remove("hidden"); }
function hideProgress() { document.getElementById("progressPanel").classList.add("hidden"); }
function showResult()   { document.getElementById("resultPanel").classList.remove("hidden"); }
function hideResult()   { document.getElementById("resultPanel").classList.add("hidden"); }

function resetAgentCards() {
    ["main","fetch","writer","review"].forEach(k => setAgentActive(k, ""));
    ["step-main","step-fetch","step-writer","step-review"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.remove("active","done");
    });
    setAgentActive("main", "active");
    setAgentStep("step-main", "active");
}

// ── Actions ───────────────────────────────────────────────────────────────────

function copyPaper() {
    if (!currentResult?.final_paper) return;
    navigator.clipboard.writeText(currentResult.final_paper)
        .then(() => showToast("📋 Paper copied to clipboard!", "success"))
        .catch(() => showToast("Copy failed — use Ctrl+A then Ctrl+C on the paper text.", "error"));
}

function downloadPaper() {
    if (!currentResult?.final_paper) return;
    const blob = new Blob([currentResult.final_paper], { type: "text/plain" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href = url;
    a.download = `ieee_paper_${(currentResult.topic || "research").replace(/[^a-z0-9]/gi, "_").slice(0, 40)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    showToast("📄 Paper downloaded!", "success");
}

function newResearch() {
    currentResult = null;
    currentResearchId = null;
    if (eventSource) { eventSource.close(); eventSource = null; }
    hideResult();
    hideProgress();
    document.getElementById("topicInput").value = "";
    document.getElementById("contextInput").value = "";
    document.getElementById("topicInput").focus();
    updateStatusBadge("active", "System Ready");
}

// ── History ───────────────────────────────────────────────────────────────────

async function loadHistory() {
    const historyList = document.getElementById("historyList");
    try {
        const res = await fetch(`${API_BASE}/api/research/history`);
        if (!res.ok) throw new Error("Failed to load history");
        const { records } = await res.json();

        if (!records.length) {
            historyList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📚</div>
                    <p>No research history yet.</p>
                    <button class="action-btn primary" onclick="showSection('generate')">Start Research</button>
                </div>`;
            return;
        }

        historyList.innerHTML = records.map(r => `
            <div class="history-item" onclick="viewHistoryItem('${r.id}')">
                <div class="history-status ${r.status}"></div>
                <div class="history-info">
                    <div class="history-topic">${escapeHtml(r.topic)}</div>
                    <div class="history-meta">${formatDate(r.created_at)} · ID: ${r.id?.slice(0, 8)}...</div>
                </div>
                <span class="history-badge ${r.status}">${r.status}</span>
            </div>`).join("");
    } catch (e) {
        historyList.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">⚠️</div>
                <p>Could not load history. ${escapeHtml(e.message)}</p>
                <p style="font-size:.8rem;color:var(--text-dim)">History requires Supabase to be configured.</p>
            </div>`;
    }
}

async function viewHistoryItem(id) {
    try {
        const res = await fetch(`${API_BASE}/api/research/result/${id}`);
        if (!res.ok) throw new Error("Result not available");
        const result = await res.json();
        currentResult = result;
        showSection("generate");
        hideProgress();
        displayResult(result);
        showToast(`📄 Loaded: ${result.topic}`, "info");
    } catch (e) {
        showToast(`Could not load result: ${e.message}`, "error");
    }
}

// ── Status Badge ──────────────────────────────────────────────────────────────

function updateStatusBadge(state, text) {
    const dot  = document.querySelector(".status-dot");
    const span = document.querySelector(".status-text");
    if (dot) { dot.className = "status-dot"; if (state) dot.classList.add(state); }
    if (span) span.textContent = text;
}

// ── Toasts ────────────────────────────────────────────────────────────────────

function showToast(message, type = "info") {
    const container = document.getElementById("toastContainer");
    if (!container) return;
    const icons = { success: "✅", error: "❌", info: "ℹ️" };
    const toast  = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${icons[type] || "ℹ️"}</span><span>${escapeHtml(message)}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.cssText += "opacity:0;transform:translateX(20px);transition:all .3s ease;";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function escapeHtml(text) {
    if (typeof text !== "string") return String(text || "");
    return text.replace(/[&<>"']/g, m => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;" })[m]);
}

function formatDate(str) {
    if (!str) return "Unknown date";
    try {
        return new Date(str).toLocaleDateString("en-US", {
            month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit"
        });
    } catch { return str; }
}
