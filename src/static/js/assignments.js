// /static/js/assignments.js  (full file — drop-in replacement)

document.addEventListener("DOMContentLoaded", function () {
    console.log("✅ Assignments.js loaded");
    if (!window.location.pathname.includes("/assignments")) return;
    if (!window.classId || window.classId === "null") {
        console.error("❌ ERROR: classId is undefined! Cannot fetch assignments.");
        return;
    }

    // Ensure globals exist even if loaders haven't run yet.
    window.assignmentStepsMap = window.assignmentStepsMap || {};
    window.assignmentProgressStepsMap = window.assignmentProgressStepsMap || {};


    fetch(`/assignments/api/scan-folder-for-new-files?class_id=${window.classId}`)
        .then(res => res.json())
        .then(() => fetchAssignments())
        .catch(() => fetchAssignments());

    const form = document.getElementById("editAssignmentForm");
    if (form) form.addEventListener("submit", submitEditForm);

    {   // keep local to avoid redeclare issues
        const p = new URLSearchParams(window.location.search);
        if (p.has("edit")) {
            p.delete("edit");
            window.history.replaceState({}, document.title, window.location.pathname);
        }
    }

    // Status dropdown: delegated
    document.body.addEventListener("change", function (event) {
        if (!event.target.classList.contains("status-dropdown")) return;

        const dropdown = event.target;
        const individualAssignmentId = dropdown.dataset.assignmentId || dropdown.dataset.individualId;
        const stepId = dropdown.dataset.stepId;
        const newStatus = dropdown.value;

        if (!individualAssignmentId || !stepId || !newStatus) {
            console.error("❌ Missing required params", { individualAssignmentId, stepId, newStatus });
            return;
        }

        fetch("/assignments/api/update-status", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                individual_assignment_id: individualAssignmentId,
                step_id: stepId,
                current_status: newStatus
            })
        })
            .then(res => res.json().then(data => ({ ok: res.ok, data })))
            .then(({ ok, data }) => {
                if (!ok || !data.success) {
                    console.error("❌ Error updating status:", data?.error || data);
                    return;
                }

                if (typeof window.updateDropdownColor === "function") {
                    window.updateDropdownColor(dropdown);
                }

                if (Array.isArray(data.updated_steps)) {
                    data.updated_steps.forEach(update => {
                        const selector = `select.status-dropdown[data-assignment-id="${update.target_individual_id}"][data-step-id="${update.step_id}"]`;
                        const linkedDropdown = document.querySelector(selector);
                        if (!linkedDropdown) {
                            console.warn("⚠️ Linked dropdown not found:", selector);
                            return;
                        }
                        linkedDropdown.value = update.child_status;
                        if (typeof window.updateDropdownColor === "function") {
                            window.updateDropdownColor(linkedDropdown);
                        }
                    });
                }
            })
            .catch(err => console.error("❌ Fetch error:", err));
    });

    // Edit button: delegated
    document.body.addEventListener("click", function (event) {
        if (!event.target.classList.contains("edit-assignment-btn")) return;

        const assignmentId = event.target.getAttribute("data-id");
        const assignmentName = event.target.getAttribute("data-name");
        const startDate = event.target.getAttribute("data-start-date");
        const completionDate = event.target.getAttribute("data-completion-date");
        const frameStart = event.target.getAttribute("data-frame-start");
        const frameEnd = event.target.getAttribute("data-frame-end");

        document.getElementById("edit-assignment-id").value = assignmentId;
        document.getElementById("edit-assignment-name").value = assignmentName;
        document.getElementById("edit-start-date").value = startDate;
        document.getElementById("edit-completion-date").value = completionDate;
        document.getElementById("edit-frame-start").value = frameStart || "";
        document.getElementById("edit-frame-end").value = frameEnd || "";

        document.getElementById("editAssignmentModal").classList.remove("hidden");
    });
});

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

/**
 * Normalize progress_step_id into an array of numeric IDs.
 * Supports: number | array | "1,2,3" | "[1,2,3]" | " 1 , 2 ".
 */
function normalizeProgressStepIds(progressStepId) {
    if (progressStepId == null || progressStepId === "" || progressStepId === "null") return [];

    // already array
    if (Array.isArray(progressStepId)) {
        return progressStepId.map(n => Number(n)).filter(n => Number.isFinite(n));
    }

    // number-ish
    if (typeof progressStepId === "number") {
        return Number.isFinite(progressStepId) ? [progressStepId] : [];
    }

    if (typeof progressStepId === "string") {
        const trimmed = progressStepId.trim();
        // JSON array string
        if (trimmed.startsWith("[") && trimmed.endsWith("]")) {
            try {
                const arr = JSON.parse(trimmed);
                return Array.isArray(arr) ? arr.map(n => Number(n)).filter(n => Number.isFinite(n)) : [];
            } catch {
                // fall through to comma parsing
            }
        }
        // comma-separated
        const parts = trimmed.split(",").map(s => Number(s.trim())).filter(n => Number.isFinite(n));
        if (parts.length) return parts;

        // last chance single number in string
        const asNum = Number(trimmed);
        return Number.isFinite(asNum) ? [asNum] : [];
    }

    return [];
}

/**
 * From all available steps for this assignment, pick only the selected progress steps.
 */
function getSelectedProgressSteps(assignment, allSteps) {
    const ids = normalizeProgressStepIds(assignment.progress_step_id);
    if (!ids.length) return [];
    // Index by id for O(1) lookup
    const byId = new Map((allSteps || []).map(s => [Number(s.id), s]));
    return ids
        .map(id => byId.get(Number(id)))
        .filter(Boolean);
}

// ─────────────────────────────────────────────────────────────
// Edit form submit
// ─────────────────────────────────────────────────────────────
function submitEditForm(event) {
    event.preventDefault();

    const assignmentId = document.getElementById("edit-assignment-id").value;
    const name = document.getElementById("edit-assignment-name").value;
    const startDate = document.getElementById("edit-start-date").value;
    const completionDate = document.getElementById("edit-completion-date").value;
    const frameStart = document.getElementById("edit-frame-start").value;
    const frameEnd = document.getElementById("edit-frame-end").value;

    fetch(`/assignments/assignments/${assignmentId}/edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            name,
            start_date: startDate,
            completion_date: completionDate,
            frame_start: frameStart || null,
            frame_end: frameEnd || null
        }),
    })
        .then(response => {
            if (!response.ok) throw new Error(`❌ HTTP ${response.status}`);
            return response.json();
        })
        .then(data => {
            if (!data.success) throw new Error(data.error || "Update failed");
            document.getElementById("editAssignmentModal").classList.add("hidden");
            fetchAssignments(); // refresh table
        })
        .catch(error => console.error("❌ Fetch error:", error));
}

// ─────────────────────────────────────────────────────────────
// Fetch assignments → load steps → build table
// ─────────────────────────────────────────────────────────────
async function fetchAssignments() {
    console.log(`📢 Fetching assignments for classId=${window.classId}`);

    try {
        const res = await fetch(`/assignments/api/view_assignments/${window.classId}`);
        if (!res.ok) throw new Error(`Server Error: ${res.status}`);
        const assignments = await res.json();

        window.assignmentsData = assignments;

        await loadAssignmentStepsMap(assignments);

        await loadAssignmentProgressStepsMap(assignments);


        updateAssignmentsTable(assignments);
    } catch (error) {
        console.error("❌ Fetch error:", error);
    }
}

// ─────────────────────────────────────────────────────────────
// Build step map for all assignments (parallel requests)
// ─────────────────────────────────────────────────────────────
async function loadAssignmentStepsMap(assignments) {
    window.assignmentStepsMap = {};
    try {
        await Promise.all(
            (assignments || []).map(async (a) => {
                const res = await fetch(`/assignments/api/steps-for-assignment?assignment_id=${a.id}`);
                const steps = res.ok ? await res.json() : [];
                window.assignmentStepsMap[a.id] = steps || [];
            })
        );
        console.log("✅ assignmentStepsMap ready:", window.assignmentStepsMap);
    } catch (err) {
        console.error("❌ Error building assignmentStepsMap:", err);
    }
}

// ─────────────────────────────────────────────────────────────
// Build map of assignment_id → [progress step ids] from join table
// ─────────────────────────────────────────────────────────────
async function loadAssignmentProgressStepsMap(assignments) {
    window.assignmentProgressStepsMap = {};
    try {
        await Promise.all(
            (assignments || []).map(async (a) => {
                const res = await fetch(`/assignments/api/assignment-progress-steps?assignment_id=${a.id}`);
                const data = res.ok ? await res.json() : [];
                window.assignmentProgressStepsMap[a.id] = (data || []).map(d => Number(d.step_id));
            })
        );
        console.log("✅ assignmentProgressStepsMap ready:", window.assignmentProgressStepsMap);
    } catch (err) {
        console.error("❌ Error building assignmentProgressStepsMap:", err);
    }
}


// ─────────────────────────────────────────────────────────────
// Table update + chart render (only selected progress steps)
// ─────────────────────────────────────────────────────────────
window.updateAssignmentsTable = function (assignments) {
    // ⛑️ Guard: skip until both maps exist at least once
    const stepMap = window.assignmentStepsMap || {};
    const progressMap = window.assignmentProgressStepsMap || {};
    if (!Object.keys(stepMap).length || !Object.keys(progressMap).length) {
        console.warn("⏳ Maps not ready yet; skipping updateAssignmentsTable this tick.");
        return;
    }
    console.log("📢 Updating assignments table dynamically:", assignments);

    const tableBody = document.getElementById("assignments-table");
    if (!tableBody) {
        console.error("❌ Table body not found!");
        return;
    }

    // optional: clear any stale charts if you kept a cache
    if (typeof window.resetCharts === "function") window.resetCharts();

    tableBody.innerHTML = "";

    assignments.forEach((assignment) => {
        const allSteps = window.assignmentStepsMap[assignment.id] || [];
        const progressStepIds = window.assignmentProgressStepsMap[assignment.id] || [];

        const selectedSteps = allSteps.filter(s => progressStepIds.includes(Number(s.id)));


        let progressCellHtml = "";

        if (selectedSteps.length > 0) {
            progressCellHtml = `
                <div class="w-full flex flex-wrap justify-center items-start gap-6">
                    ${selectedSteps.map((step, index) => `
                        <div class="flex flex-col items-center">
                            <div class="text-xs text-gray-300 mb-1 text-center">${step.name}</div>
                            <canvas id="chart-${assignment.id}-${index}" width="100" height="100" class="w-24 h-24 mx-auto"></canvas>
                        </div>
                    `).join("")}
                </div>
            `;
        } else {
            // why: user did not choose progress steps (yet) or IDs don’t match local step list
            progressCellHtml = `<div class="text-sm text-gray-400 italic">No progress tracking steps selected</div>`;
        }

        const row = document.createElement("tr");
        row.classList.add("border-b", "hover:bg-gray-700");
        row.innerHTML = `
            <td class="p-3 border-b" style="width: 300px;">
                <a href="/assignments/${assignment.id}/individual?class_id=${window.classId}" class="text-white">
                    ${assignment.name || 'N/A'}
                </a>
            </td>
            <td class="p-3 border-b" style="width: 120px;">${assignment.start_date || 'N/A'}</td>
            <td class="p-3 border-b" style="width: 120px;">${assignment.completion_date || 'N/A'}</td>
            <td class="p-3 border-b" style="width: 100px;">${assignment.frame_start ?? ''}</td>
            <td class="p-3 border-b" style="width: 100px;">${assignment.frame_end ?? ''}</td>
            <td class="p-3 border-b align-top" style="width: 500px;">
                ${progressCellHtml}
            </td>
            <td class="p-3 border-b align-top text-center" style="width: 180px;">
                <button class="edit-assignment-btn bg-yellow-800 hover:bg-yellow-600 text-white px-3 py-1 rounded-lg mb-2"
                    data-id="${assignment.id}"
                    data-name="${assignment.name}"
                    data-start-date="${assignment.start_date}"
                    data-completion-date="${assignment.completion_date}"
                    data-frame-start="${assignment.frame_start ?? ''}"
                    data-frame-end="${assignment.frame_end ?? ''}">
                    Edit
                </button><br>
                <button class="bg-red-800 hover:bg-red-600 text-white px-3 py-1 rounded-lg"
                    onclick="confirmDelete(${assignment.id}, event)">
                    Delete
                </button>
            </td>
        `;
        tableBody.appendChild(row);

        // Render charts only for selected progress steps
        selectedSteps.forEach((step, index) => {
            const canvasId = `chart-${assignment.id}-${index}`;
            if (typeof window.fetchChartData === "function") {
                window.fetchChartData(assignment.id, step.id, assignment.parent_step_id, canvasId);
            } else {
                console.warn("⚠️ fetchChartData not available yet.");
            }
        });
    });

    console.log("✅ Table updated; filtered charts queued.");
};

// ─────────────────────────────────────────────────────────────
// Misc helpers
// ─────────────────────────────────────────────────────────────
function switchAssignment(url) {
    window.location.href = url;
}

window.changeClass = function (selectedClassUrl) {
    if (selectedClassUrl) {
        window.location.href = selectedClassUrl;
    } else {
        console.warn("⚠️ No class selected.");
    }
};

window.confirmDelete = function (assignmentId, event) {
    event.stopPropagation();
    Swal.fire({
        title: "Are you sure?",
        text: "This action cannot be undone.",
        icon: "warning",
        showCancelButton: true,
        confirmButtonColor: "#d33",
        cancelButtonColor: "#3085d6",
        confirmButtonText: "Yes, delete it!",
        cancelButtonText: "Cancel"
    }).then((result) => {
        if (result.isConfirmed) {
            fetch(`/assignments/assignments/${assignmentId}/delete`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        Swal.fire("Deleted!", "The assignment has been deleted.", "success")
                            .then(() => { location.reload(); });
                    } else {
                        Swal.fire("Error!", data.error || "Failed to delete the assignment.", "error");
                    }
                })
                .catch(error => {
                    console.error("❌ Error:", error);
                    Swal.fire("Error!", "An error occurred while deleting the assignment.", "error");
                });
        }
    });
};

function openEditModal(id, name, startDate, completionDate, frameStart, frameEnd) {
    document.getElementById("edit-assignment-id").value = id;
    document.getElementById("edit-assignment-name").value = name;
    document.getElementById("edit-start-date").value = startDate;
    document.getElementById("edit-completion-date").value = completionDate;
    document.getElementById("edit-frame-start").value = frameStart || "";
    document.getElementById("edit-frame-end").value = frameEnd || "";
    document.getElementById("editAssignmentModal").classList.remove("hidden");
}

function closeEditModal() {
    document.getElementById("editAssignmentModal").classList.add("hidden");
}
