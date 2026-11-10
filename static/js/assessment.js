/**
 * Career Readiness Assessment — Interactive Client Engine
 * Handles:
 * - Live countdown timer with automatic expiry submission
 * - Question palette navigation & state updates
 * - Background auto-saving of multiple-choice and coding answers
 * - Isolated "Run Sample Code" AJAX integration with live output console
 * - Code editor keyboard ergonomics (Tab key indentation)
 * - Submission confirmation modal with answered / unanswered question count
 */

(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        const testContainer = document.querySelector(".test-layout-shell");
        if (!testContainer) return; // Only run on active test-taking screen

        const sessionId = testContainer.dataset.sessionId;
        let currentIndex = 0;
        const totalQuestions = parseInt(testContainer.dataset.totalQuestions || "0", 10);
        let remainingSeconds = parseInt(testContainer.dataset.remainingSeconds || "3600", 10);
        let saveTimeout = null;

        // Elements
        const timerDisplay = document.getElementById("timer-display");
        const timerPill = document.getElementById("timer-pill");
        const questionCards = Array.from(document.querySelectorAll(".question-item-card"));
        const paletteButtons = Array.from(document.querySelectorAll(".palette-btn"));
        const prevBtn = document.getElementById("prev-q-btn");
        const nextBtn = document.getElementById("next-q-btn");
        const saveStatus = document.getElementById("save-status-text");
        const submitTestBtn = document.getElementById("submit-test-btn");
        const submitModal = document.getElementById("submit-confirm-modal");
        const modalAnsweredCount = document.getElementById("modal-answered-count");
        const modalUnansweredCount = document.getElementById("modal-unanswered-count");
        const cancelSubmitBtn = document.getElementById("cancel-submit-btn");
        const confirmSubmitBtn = document.getElementById("confirm-submit-btn");
        const finalSubmitForm = document.getElementById("final-submit-form");

        // ── 1. Live Countdown Timer ─────────────────────────────────────────
        function updateTimerDisplay() {
            if (remainingSeconds <= 0) {
                if (timerDisplay) timerDisplay.textContent = "00:00";
                // Auto-submit test on timer expiry
                if (finalSubmitForm) {
                    finalSubmitForm.submit();
                }
                return;
            }

            const mins = Math.floor(remainingSeconds / 60);
            const secs = remainingSeconds % 60;
            const formatted = `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;

            if (timerDisplay) timerDisplay.textContent = formatted;

            // Warning style when under 5 minutes (300s)
            if (remainingSeconds <= 300 && timerPill) {
                timerPill.classList.add("timer-warning");
            }

            remainingSeconds--;
        }

        updateTimerDisplay();
        const timerInterval = setInterval(updateTimerDisplay, 1000);

        // ── 2. Question Navigation ──────────────────────────────────────────
        function showQuestion(index) {
            if (index < 0 || index >= totalQuestions) return;
            currentIndex = index;

            questionCards.forEach((card, idx) => {
                card.style.display = idx === index ? "block" : "none";
            });

            paletteButtons.forEach((btn, idx) => {
                btn.classList.toggle("btn-active", idx === index);
            });

            if (prevBtn) prevBtn.disabled = index === 0;
            if (nextBtn) {
                if (index === totalQuestions - 1) {
                    nextBtn.textContent = "Review & Submit →";
                } else {
                    nextBtn.textContent = "Next →";
                }
            }
        }

        paletteButtons.forEach((btn) => {
            btn.addEventListener("click", () => {
                const targetIdx = parseInt(btn.dataset.index, 10);
                showQuestion(targetIdx);
            });
        });

        if (prevBtn) {
            prevBtn.addEventListener("click", () => {
                if (currentIndex > 0) showQuestion(currentIndex - 1);
            });
        }

        if (nextBtn) {
            nextBtn.addEventListener("click", () => {
                if (currentIndex < totalQuestions - 1) {
                    showQuestion(currentIndex + 1);
                } else {
                    openSubmitModal();
                }
            });
        }

        // Initialize to first question
        showQuestion(0);

        // ── 3. Background Auto-Saving ────────────────────────────────────────
        function triggerSave(questionId, selectedOption, codeSubmission, qIndex) {
            if (saveStatus) {
                saveStatus.textContent = "Saving…";
                saveStatus.style.opacity = "1";
            }

            fetch("/assessment/api/save-answer", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    session_id: sessionId,
                    question_id: questionId,
                    selected_option: selectedOption,
                    code_submission: codeSubmission,
                }),
            })
                .then((res) => res.json())
                .then((data) => {
                    if (data.success) {
                        if (saveStatus) saveStatus.textContent = "● Saved";
                        // Update palette button visual state
                        const isAnswered = Boolean(selectedOption || (codeSubmission && codeSubmission.trim().length > 0));
                        if (paletteButtons[qIndex]) {
                            paletteButtons[qIndex].classList.toggle("btn-answered", isAnswered);
                        }
                    } else {
                        if (saveStatus) saveStatus.textContent = "Save error";
                    }
                })
                .catch(() => {
                    if (saveStatus) saveStatus.textContent = "Connection offline";
                });
        }

        // Multiple choice option selection listener
        document.querySelectorAll(".mcq-option-radio").forEach((radio) => {
            radio.addEventListener("change", function () {
                const qCard = this.closest(".question-item-card");
                const qId = qCard.dataset.questionId;
                const qIdx = parseInt(qCard.dataset.index, 10);
                triggerSave(qId, this.value, null, qIdx);
            });
        });

        // Code editor textarea input listener with debouncing & Tab key handling
        document.querySelectorAll(".code-textarea").forEach((textarea) => {
            textarea.addEventListener("keydown", function (e) {
                if (e.key === "Tab") {
                    e.preventDefault();
                    const start = this.selectionStart;
                    const end = this.selectionEnd;
                    this.value = this.value.substring(0, start) + "    " + this.value.substring(end);
                    this.selectionStart = this.selectionEnd = start + 4;
                }
            });

            textarea.addEventListener("input", function () {
                const qCard = this.closest(".question-item-card");
                const qId = qCard.dataset.questionId;
                const qIdx = parseInt(qCard.dataset.index, 10);

                clearTimeout(saveTimeout);
                saveTimeout = setTimeout(() => {
                    triggerSave(qId, null, textarea.value, qIdx);
                }, 800);
            });
        });

        // ── 4. Isolated Sample Code Execution ───────────────────────────────
        document.querySelectorAll(".run-code-btn").forEach((btn) => {
            btn.addEventListener("click", function () {
                const qCard = this.closest(".question-item-card");
                const qId = qCard.dataset.questionId;
                const qIdx = parseInt(qCard.dataset.index, 10);
                const lang = qCard.dataset.language;
                const textarea = qCard.querySelector(".code-textarea");
                const consoleEl = qCard.querySelector(".code-console-output");

                if (!textarea || !consoleEl) return;
                const code = textarea.value;

                // Save first
                triggerSave(qId, null, code, qIdx);

                // UI loading state
                btn.disabled = true;
                const origText = btn.innerHTML;
                btn.innerHTML = "Executing…";
                consoleEl.textContent = "Compiling and running sample test cases in isolated sandbox…\n";

                fetch("/assessment/api/run-code", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        session_id: sessionId,
                        question_id: qId,
                        code: code,
                        language: lang,
                    }),
                })
                    .then((res) => res.json())
                    .then((result) => {
                        btn.disabled = false;
                        btn.innerHTML = origText;

                        if (result.error) {
                            consoleEl.innerHTML = `<span class="console-test-fail">Execution Error:</span>\n${result.error}`;
                            return;
                        }

                        let outputLines = [];
                        outputLines.push(`[${lang.toUpperCase()} RUNNER] Passed ${result.passed_tests} / ${result.total_tests} sample test cases.\n`);

                        (result.test_results || []).forEach((tc, i) => {
                            const icon = tc.passed ? "✔ PASS" : "✖ FAIL";
                            const colorClass = tc.passed ? "console-test-pass" : "console-test-fail";
                            outputLines.push(`<span class="${colorClass}">${icon} Test Case ${i + 1} (${tc.execution_time_ms} ms)</span>`);
                            outputLines.push(`  Input:    ${tc.input || "None"}`);
                            outputLines.push(`  Expected: ${tc.expected_output}`);
                            outputLines.push(`  Actual:   ${tc.actual_output}`);
                            if (tc.error) {
                                outputLines.push(`  Error:    ${tc.error}`);
                            }
                            outputLines.push("");
                        });

                        consoleEl.innerHTML = outputLines.join("\n");
                    })
                    .catch((err) => {
                        btn.disabled = false;
                        btn.innerHTML = origText;
                        consoleEl.innerHTML = `<span class="console-test-fail">Network error running code:</span> ${err.message}`;
                    });
            });
        });

        // ── 5. Confirmation Modal & Final Submission ─────────────────────────
        function openSubmitModal() {
            let answered = 0;
            paletteButtons.forEach((btn) => {
                if (btn.classList.contains("btn-answered")) answered++;
            });
            const unanswered = totalQuestions - answered;

            if (modalAnsweredCount) modalAnsweredCount.textContent = String(answered);
            if (modalUnansweredCount) modalUnansweredCount.textContent = String(unanswered);
            if (submitModal) submitModal.style.display = "grid";
        }

        if (submitTestBtn) {
            submitTestBtn.addEventListener("click", openSubmitModal);
        }

        if (cancelSubmitBtn) {
            cancelSubmitBtn.addEventListener("click", () => {
                if (submitModal) submitModal.style.display = "none";
            });
        }

        if (confirmSubmitBtn && finalSubmitForm) {
            confirmSubmitBtn.addEventListener("click", () => {
                confirmSubmitBtn.disabled = true;
                confirmSubmitBtn.textContent = "Finalizing Assessment…";
                finalSubmitForm.submit();
            });
        }
    });
})();
