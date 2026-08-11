document.addEventListener("DOMContentLoaded", function () {
    console.log("✅ assets.js loaded");

    function fetchAssetCategoryProgress() {
        if (!window.filmId) {
            console.error("❌ filmId is not defined!");
            return;
        }
        fetch(`/films/films/${window.filmId}/api/asset_categories`)
            .then(response => response.json())
            .then(data => {
                console.log("✅ Category progress:", data);
                updateCategoryTable(data);
            })
            .catch(error => console.error("Error fetching category data:", error));
    }

    function updateCategoryTable(categories) {
        const tableBody = document.getElementById("assets-table");
        
        tableBody.innerHTML = "";

        categories.forEach(category => {
            const row = document.createElement("tr");

            const progressCharts = category.steps.map((step, i) => {
                const labels = Object.keys(step.statuses);
                const values = Object.values(step.statuses);

                // Get colors from step.nodes passed from backend
                const colors = labels.map(status => {
                    const node = step.nodes?.find(n => n.name === status);
                    return node?.color || "#999";
                });

                const chartId = `chart-${category.category.replace(/\\s+/g, '-')}-${i}`;
                setTimeout(() => renderPieChart(chartId, labels, values, colors), 0);

                return `
                    <div class='text-center'>
                        <canvas id='${chartId}' width='80' height='80'></canvas>
                        <div class='text-xs mt-1'>${step.step_name}</div>
                    </div>
                `;
            }).join("");

            row.innerHTML = `
                <td class="p-3 font-semibold text-white cursor-pointer"
                    onclick="location.href='/films/films/assets/category/${encodeURIComponent(category.category)}?film_id=${window.filmId}'">
                    ${category.category}
                </td>
                <td class="p-3 flex flex-wrap gap-3">${progressCharts}</td>

            `;
            tableBody.appendChild(row);
        });
    }


    if (typeof window.filmId === 'undefined' || !window.filmId) {
        const filmIdElement = document.getElementById("film-dropdown");
        if (filmIdElement) {
            const selectedFilmId = filmIdElement.value.trim();
            if (selectedFilmId) {
                window.filmId = selectedFilmId;
                console.log(`📝 Film ID (from dropdown): ${window.filmId}`);
                if (document.getElementById("assets-table")) {
                    fetchAssetCategoryProgress();
                }
            }
        }
    } else {
        console.log(`📝 Film ID (from template): ${window.filmId}`);
        if (document.getElementById("assets-table")) {
            fetchAssetCategoryProgress();
        }
    }

    const filmDropdown = document.getElementById("film-dropdown");
    if (filmDropdown) {
        filmDropdown.addEventListener("change", (event) => {
            const newFilmId = event.target.value.trim();
            if (newFilmId) {
                window.filmId = newFilmId;
                console.log(`🔄 Film ID changed to: ${window.filmId}`);
                fetchAssetCategoryProgress();
            }
        });
    }

    function initIndividualAssetUI() {
        console.log("✅ Initializing individual asset view UI");

        // STATUS CHANGE
        // STATUS CHANGE
        document.querySelectorAll("select[name^='status-']").forEach(dropdown => {
            dropdown.addEventListener("change", function () {
                const assignmentId = this.name.split("-")[1];
                const nodeId = this.value;

                const stepDiv = this.closest("[data-step-id]");
                const stepId = stepDiv?.dataset.stepId;
                const assetRow = this.closest(".flex[data-asset-id]");
                const assetId = assetRow?.dataset?.assetId;

                if (!stepId || !assetId) {
                    console.error("❌ stepId or assetId not found.");
                    return;
                }

                // ✅ Optimistically recolor this dropdown right away
                const selectedOption = this.options[this.selectedIndex];
                const optimisticColor = selectedOption.style.backgroundColor;
                if (optimisticColor) this.style.backgroundColor = optimisticColor;

                let indicator = document.createElement("div");
                indicator.className = "text-green-400 text-xs mt-1 animate-pulse";
                indicator.textContent = "Saving...";
                const parent = this.parentElement;
                parent.querySelectorAll(".text-green-400").forEach(el => el.remove());
                parent.appendChild(indicator);

                fetch(`/films/assets/${assetId}/steps/${stepId}/update`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ node_id: nodeId })
                }).then(res => res.json())
                    .then(data => {
                        console.log("✅ Status updated", data);

                        if (!data.success) {
                            throw new Error(data.message || "Update failed");
                        }

                        indicator.textContent = "Saved ✅";
                        indicator.classList.remove("animate-pulse");

                        // ✅ Confirm this dropdown's color from the server
                        if (data.color) this.style.backgroundColor = data.color;

                        // 🔁 Apply crossflow updates to other dropdowns for this asset, no reload needed
                        (data.updated_steps || []).forEach(step => {
                            const otherStepDiv = assetRow.querySelector(`[data-step-id="${step.step_id}"]`);
                            const otherSelect = otherStepDiv?.querySelector("select[name^='status-']");
                            if (otherSelect) {
                                otherSelect.value = step.node_id;
                                otherSelect.style.backgroundColor = step.color;
                            }
                        });

                        setTimeout(() => indicator.remove(), 3000);
                    })
                    .catch(err => {
                        console.error("❌ Error:", err);
                        indicator.textContent = "Error ❌";
                        indicator.classList.remove("animate-pulse");
                        indicator.classList.add("text-red-400");
                    });
            });
        });
        


        // USER CHANGE
        document.querySelectorAll("select[name^='user-']").forEach(dropdown => {
            dropdown.addEventListener("change", function () {
                const assignmentId = this.name.split("-")[1];
                const userId = this.value;

                fetch(`/films/assets/steps/${assignmentId}/assign_user`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ user_id: userId })
                }).then(res => res.json())
                    .then(data => {
                        console.log("👤 User updated", data);
                        location.reload();
                    });
            });
        });

        // DUE DATE CHANGE
        document.querySelectorAll("input[name^='due_date-']").forEach(input => {
            input.addEventListener("change", function () {
                const assignmentId = this.name.split("-")[1];
                const dueDate = this.value;

                fetch(`/films/assets/steps/${assignmentId}/update_due_date`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ due_date: dueDate })
                }).then(res => res.json())
                    .then(data => {
                        console.log("📅 Due date updated", data);
                        location.reload();
                    });
            });
        });
    }


    const checkboxes = document.querySelectorAll(".step-toggle");
    const artistToggle = document.getElementById("artist-only-toggle");

    checkboxes.forEach(cb => {
        cb.addEventListener("change", () => {
            const stepId = cb.dataset.stepId;
            const visible = cb.checked;
            document.querySelectorAll(`[data-step-id='${stepId}']`).forEach(el => {
                el.style.display = visible ? "" : "none";
            });
        });
    });

    artistToggle?.addEventListener("change", () => {
        const artistOnly = artistToggle.checked;
        checkboxes.forEach(cb => {
            const name = cb.dataset.stepName || "";
            const isFB = name.includes("FB");
            cb.checked = artistOnly ? !isFB : true;

            const stepId = cb.dataset.stepId;
            const visible = cb.checked;
            document.querySelectorAll(`[data-step-id='${stepId}']`).forEach(el => {
                el.style.display = visible ? "" : "none";
            });
        });
    });





    // Run only if we're on the individual asset view
    // ✅ Correct: directly call the initializer
    if (document.querySelector("form[action='#']")) {
        console.log("🧠 initIndividualAssetUI fired!");

        initIndividualAssetUI();
    }

});

function toggleFilters() {
    const box = document.getElementById("filter-box");
    box?.classList.toggle("hidden");
}

function openBulkEditModal() {
    const selected = Array.from(document.querySelectorAll('input[name="asset_ids"]:checked'));
    if (selected.length === 0) {
        alert("No assets selected");
        return;
    }
    const ids = selected.map(cb => cb.value.trim()).join(",");
    document.getElementById("bulk-asset-ids").value = ids;
    document.getElementById("bulkEditModal").classList.remove("hidden");
}

function closeBulkEditModal() {
    document.getElementById("bulkEditModal").classList.add("hidden");
}

document.getElementById("edit-selected-btn")?.addEventListener("click", openBulkEditModal);

document.getElementById("delete-selected-btn")?.addEventListener("click", () => {
    const selected = Array.from(document.querySelectorAll('input[name="asset_ids"]:checked'));
    if (selected.length === 0) {
        Swal.fire("No assets selected", "Please select at least one asset to delete.", "warning");
        return;
    }

    const ids = selected.map(cb => cb.value.trim());

    Swal.fire({
        title: "Are you sure?",
        text: `You are about to delete ${ids.length} asset(s). This cannot be undone.`,
        icon: "warning",
        showCancelButton: true,
        confirmButtonText: "Yes, delete",
        confirmButtonColor: "#d33"
    }).then(result => {
        if (result.isConfirmed) {
            fetch("/films/films/assets/delete_assets", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ asset_ids: ids })
            })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        Swal.fire("Deleted!", data.message, "success").then(() => location.reload());
                    } else {
                        Swal.fire("Error", data.message, "error");
                    }
                });
        }
    });
});

function openUploadDesignModal(assetName, category, filmName) {
    document.getElementById("uploadDesignModal").classList.remove("hidden");
    document.getElementById("filmNameField").value = filmName;
    document.getElementById("assetCategoryField").value = category;
    document.getElementById("assetNameField").value = assetName;
}

function closeDesignModal() {
    document.getElementById("uploadDesignModal").classList.add("hidden");
}

document.getElementById("designUploadForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();

    const form = e.target;
    const files = form.querySelector("#designFiles").files;
    const maxFileSizeMB = 50; // limit per file
    const maxTotalSizeMB = 200; // total batch limit

    let totalSize = 0;
    for (const f of files) totalSize += f.size;

    if (Array.from(files).some(f => f.size > maxFileSizeMB * 1024 * 1024)) {
        Swal.fire({
            icon: "warning",
            title: "File Too Large",
            text: `Each file must be under ${maxFileSizeMB} MB.`,
        });
        return;
    }

    if (totalSize > maxTotalSizeMB * 1024 * 1024) {
        Swal.fire({
            icon: "warning",
            title: "Upload Too Large",
            text: `Total upload size must be under ${maxTotalSizeMB} MB.`,
        });
        return;
    }

    const formData = new FormData(form);

    try {
        const res = await fetch("/films/assets/upload_designs", {
            method: "POST",
            body: formData
        });

        const data = await res.json();

        if (data.success) {
            Swal.fire({
                icon: "success",
                title: "Upload Complete",
                text: `${data.files.length} file(s) uploaded successfully.`,
                confirmButtonColor: "#3085d6"
            }).then(() => {
                closeDesignModal();
            });
        } else {
            Swal.fire({
                icon: "error",
                title: "Upload Failed",
                text: data.message || "Something went wrong.",
            });
        }
    } catch (err) {
        Swal.fire({
            icon: "error",
            title: "Upload Error",
            text: "Server could not handle the upload. Try fewer or smaller files.",
        });
        console.error("Upload error:", err);
    }
});

