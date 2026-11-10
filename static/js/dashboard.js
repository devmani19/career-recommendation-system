/**
 * CareerAI Dashboard — Interactive behaviour
 * Handles: tab navigation, file selection display, form loading state
 */

/* ── Tab system ────────────────────────────────────────────────────────── */

const moduleTabs = Array.from(document.querySelectorAll("[role='tab'][data-module-tab]"));

function activateModule(tab, moveFocus = false) {
    const activeModule = tab.dataset.moduleTab;

    moduleTabs.forEach((t) => {
        const isActive = t === tab;
        t.setAttribute("aria-selected", String(isActive));
        t.tabIndex = isActive ? 0 : -1;

        const panel = document.getElementById(`module-${t.dataset.moduleTab}`);
        if (panel) panel.hidden = !isActive;
    });

    const workspace = document.querySelector(".module-workspace");
    if (workspace) workspace.setAttribute("data-active-module", activeModule);

    if (moveFocus) tab.focus();
}

moduleTabs.forEach((tab) => {
    tab.addEventListener("click", () => activateModule(tab));

    tab.addEventListener("keydown", (e) => {
        const idx = moduleTabs.indexOf(tab);
        let next = idx;

        if (e.key === "ArrowRight") next = (idx + 1) % moduleTabs.length;
        else if (e.key === "ArrowLeft") next = (idx - 1 + moduleTabs.length) % moduleTabs.length;
        else if (e.key === "Home") next = 0;
        else if (e.key === "End") next = moduleTabs.length - 1;
        else return;

        e.preventDefault();
        activateModule(moduleTabs[next], true);
    });
});

/* Open a specific tab from any in-page button */
document.querySelectorAll("[data-open-module]").forEach((btn) => {
    btn.addEventListener("click", () => {
        const target = moduleTabs.find((t) => t.dataset.moduleTab === btn.dataset.openModule);
        if (target) activateModule(target, true);
    });
});

/* ── File selection display ────────────────────────────────────────────── */

function displaySelectedFiles(input, output, emptyMessage) {
    if (!input || !output) return;

    input.addEventListener("change", () => {
        const files = Array.from(input.files || []);

        if (files.length === 0) {
            output.textContent = emptyMessage;
            return;
        }

        const names = files.map((f) => f.name);
        output.textContent =
            names.length > 2
                ? `${names.slice(0, 2).join(", ")} and ${names.length - 2} more`
                : names.join(", ");
    });
}

displaySelectedFiles(
    document.getElementById("resume-file"),
    document.getElementById("resume-file-name"),
    "No resume selected"
);

displaySelectedFiles(
    document.getElementById("certificate-files"),
    document.getElementById("certificate-file-name"),
    "No certificates selected"
);

/* ── Form loading state ────────────────────────────────────────────────── */

const analysisForm = document.getElementById("analysis-form");
const analyzeBtn   = document.getElementById("analyze-btn");

if (analysisForm && analyzeBtn) {
    analysisForm.addEventListener("submit", (e) => {
        /* Basic client-side guard — server will validate fully */
        const resumeInput = document.getElementById("resume-file");
        const certInput   = document.getElementById("certificate-files");

        if (!resumeInput || !resumeInput.files.length) {
            e.preventDefault();
            showInlineError("Please select a resume file before submitting.");
            return;
        }

        /* Show loading state without breaking form dispatch */
        analyzeBtn.classList.add("loading");
        analyzeBtn.style.pointerEvents = "none";
        const textEl = analyzeBtn.querySelector(".btn-text");
        if (textEl) textEl.textContent = "Analyzing…";
        setTimeout(() => { analyzeBtn.disabled = true; }, 50);
    });
}

function showInlineError(message) {
    /* Remove any existing inline error */
    const existing = document.getElementById("client-error");
    if (existing) existing.remove();

    const div = document.createElement("div");
    div.id = "client-error";
    div.className = "alert error";
    div.setAttribute("role", "alert");
    div.textContent = message;
    div.style.marginTop = "12px";

    if (analysisForm) analysisForm.after(div);
    div.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* ── Async REST API client helper ────────────────────────────────────────── */
async function fetchCareerRecommendations(profileData) {
    try {
        const response = await fetch("/api/v1/recommendations", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(profileData),
        });
        return await response.json();
    } catch (err) {
        console.error("API recommendation request failed:", err);
        return { success: false, error: err.message };
    }
}
window.fetchCareerRecommendations = fetchCareerRecommendations;