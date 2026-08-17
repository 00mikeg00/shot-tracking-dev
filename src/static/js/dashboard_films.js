// dashboard_films.js

// Film shot dashboard ONLY — no assignments/classes
// Handles:
// - Loading user film shots
// - Updating shot status
// - Color-coded dropdowns
// - Sort by field/direction



let filmShotsSort = {
  field: "shot_number",
  direction: "asc"
};

document.addEventListener("DOMContentLoaded", () => {
  fetchDashboardFilmShots();
  renderUserAssets();

  const sortField = document.getElementById("sortField");
  const toggleDir = document.getElementById("toggleSortDirection");

  sortField?.addEventListener("change", () => {
    filmShotsSort.field = sortField.value;
    fetchDashboardFilmShots();
  });

  toggleDir?.addEventListener("click", () => {
    filmShotsSort.direction = filmShotsSort.direction === "asc" ? "desc" : "asc";
    toggleDir.textContent = filmShotsSort.direction === "asc" ? "⬆ Asc" : "⬇ Desc";
    fetchDashboardFilmShots();
  });
});

function updateDropdownColor(selectElement) {
  const selectedOption = selectElement.options[selectElement.selectedIndex];
  const color = selectedOption?.getAttribute("data-color") || selectedOption?.style.backgroundColor;

  if (color) {
    selectElement.style.backgroundColor = color;
    selectElement.style.color = "#000";     // readable text, just like assignments
    selectElement.style.border = `2px solid ${color}`;
  } else {
    selectElement.style.backgroundColor = "";
    selectElement.style.color = "";
    selectElement.style.border = "";
  }
}


function handleFilmStatusChange(selectEl) {
  updateDropdownColor(selectEl);

  const newStatus = selectEl.value;
  const stepId = parseInt(selectEl.getAttribute("data-step-id"), 10);

  let sceneId = selectEl.getAttribute("data-scene-id");
  let shotId = selectEl.getAttribute("data-shot-id");

  // Fallbacks if attributes are missing
  if (!sceneId || sceneId === "null" || sceneId === "")
    sceneId = selectEl.closest("tr")?.getAttribute("data-scene-id");
  if (!shotId || shotId === "null" || shotId === "")
    shotId = selectEl.closest("tr")?.getAttribute("data-shot-id");

  sceneId = sceneId ? parseInt(sceneId, 10) : null;
  shotId = shotId ? parseInt(shotId, 10) : null;

  const isScene = sceneId !== null && !isNaN(sceneId);
  const isShot = shotId !== null && !isNaN(shotId);

  const payload = {
    task_type: isScene ? "scene" : isShot ? "shot" : null,
    task_id: isScene ? sceneId : shotId,
    step_id: stepId,
    new_status: newStatus
  };

  console.log("🔁 Sending payload:", payload);

  if (!payload.task_type || !payload.task_id || !payload.step_id || !payload.new_status) {
    console.error("❌ Missing required fields in payload", payload);
    Swal.fire({
      icon: "error",
      title: "Bad Data",
      text: "Missing required fields to update status.",
      toast: true,
      position: "top-end",
      timer: 3000,
      showConfirmButton: false
    });
    return;
  }

  fetch("/dashboard/api/update-status", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  })
    .then(res => {
      if (!res.ok) throw new Error("Failed to update");
      return res.json();
    })
    .then(data => {
      console.log("✅ Update response:", data);

      // Thumbnail responses skip DB write
      if (data.message && data.message.includes("Thumbnail")) {
        console.log("Local-only update for thumbnail:", payload);
        updateLocalStatus(payload.task_id, payload.step_id, payload.new_status);
      } else if (data.message === "Status updated successfully") {
        updateLocalStatus(payload.task_id, payload.step_id, payload.new_status);
      }

      Swal.fire({
        icon: "success",
        title: "Status Updated",
        text: `Status set to "${newStatus}"`,
        toast: true,
        position: "top-end",
        timer: 2000,
        showConfirmButton: false
      });


      console.log("📡 Triggering crossflow:", { sceneId, stepId, newStatus });

      // ✅ Trigger crossflow update if scene step
      // if (isScene) {
      //   fetch("/films/api/scene_progress/crossflow", {
      //     method: "POST",
      //     headers: { "Content-Type": "application/json" },
      //     body: JSON.stringify({
      //       scene_id: sceneId,
      //       step_id: stepId,
      //       status: newStatus
      //     })
      //   })
      //     .then(res => {
      //       if (!res.ok) throw new Error("Crossflow failed");
      //       return res.json();
      //     })
      //     .then(d => console.log("🔁 Crossflow updated:", d))
      //     .catch(err => console.error("❌ Crossflow failed", err));
      // }
    })
    .catch(err => {
      console.error("❌ Error updating status", err);
      Swal.fire({
        icon: "error",
        title: "Update Failed",
        text: "Could not save status. Try again.",
        toast: true,
        position: "top-end",
        timer: 3000,
        showConfirmButton: false
      });
    });
}


// Same not-started/in-progress/approved bucketing as the assignments
// dashboard's computeAssignmentBadge, adapted to film steps' field names
// (status, not assignment_status; no server-computed current_step here).
function computeShotBadge(steps) {
  let anyInProgress = false;
  let allTerminal = steps.length > 0;

  for (const step of steps) {
    const opts = step.dropdown_options || [];
    const first = opts[0]?.name;
    const last = opts[opts.length - 1]?.name;
    const status = step.status;
    const isTerminal = opts.length > 0 && status === last;
    const isNotStarted = !status || (opts.length > 0 && status === first);

    if (!isTerminal) allTerminal = false;
    if (!isNotStarted && !isTerminal) anyInProgress = true;
  }

  if (anyInProgress) return { label: "In progress", cls: "bg-yellow-600 text-yellow-100" };
  if (allTerminal) return { label: "Approved", cls: "bg-green-700 text-green-100" };
  return { label: "Not started", cls: "bg-gray-600 text-gray-200" };
}

function buildShotStatusDropdown(shot, step) {
  const dropdown = document.createElement("select");
  dropdown.className = "status-dropdown bg-gray-200 text-black px-2 py-1 rounded text-sm cursor-pointer";
  dropdown.setAttribute("data-step-id", step.step_id);

  const isThumbnail = shot.shot_number === "—" || shot.shot_number === "-";

  if (isThumbnail && shot.scene_id != null) {
    // Thumbnails use scene-level updates
    dropdown.setAttribute("data-scene-id", shot.scene_id);
    dropdown.setAttribute("data-task-type", "scene");
  } else if (shot.shot_id != null) {
    // Real shots
    dropdown.setAttribute("data-shot-id", shot.shot_id);
    dropdown.setAttribute("data-task-type", "shot");
  }

  (step.dropdown_options || []).forEach(opt => {
    const option = document.createElement("option");
    option.value = opt.name;
    option.textContent = opt.name;
    option.selected = (opt.name?.toLowerCase() === (step.status || "").toLowerCase());
    option.style.backgroundColor = opt.color;
    option.setAttribute("data-color", opt.color);
    dropdown.appendChild(option);
  });

  dropdown.onchange = () => handleFilmStatusChange(dropdown);
  setTimeout(() => updateDropdownColor(dropdown), 0);

  return dropdown;
}

async function fetchDashboardFilmShots() {
  try {
    console.log("📡 Fetching dashboard data...");

    const selectedUser = document.getElementById("userSelect")?.value;
    const url = selectedUser
      ? `/films/api/film/dashboard_data?user_id=${selectedUser}`
      : `/films/api/film/dashboard_data`;

    const res = await fetch(url);

    const text = await res.text();
    const films = JSON.parse(text);
    const container = document.getElementById("todo-film-shots");
    container.innerHTML = "";

    if (!Array.isArray(films) || films.length === 0) {
      console.log("🎯 Fetched films:", films);
      container.innerHTML = `<div class="text-gray-400 p-3">No shots assigned.</div>`;
      return;
    }

    films.forEach((film, index) => {
      if (!film.shots || film.shots.length === 0) return;

      film.shots = sortShots(film.shots);

      const filmToggleId = `film-${index}`;

      const filmSection = document.createElement("div");
      filmSection.className = "bg-gray-800 rounded-lg overflow-hidden mb-4";

      const filmHeader = document.createElement("div");
      filmHeader.className = "flex justify-between items-center bg-gray-600 px-4 py-3 cursor-pointer";
      filmHeader.innerHTML = `
        <div class="flex items-center gap-2">
          <span class="chevron text-white">▾</span>
          <span class="text-white font-bold text-lg">${film.title}</span>
        </div>
      `;

      const scriptBtn = document.createElement("a");
      scriptBtn.textContent = "📜 View Script";
      scriptBtn.href = `/dashboard/films/get_script/${encodeURIComponent(film.title)}`;
      scriptBtn.target = "_blank";
      scriptBtn.className = "bg-green-700 hover:bg-green-800 text-white px-3 py-1 rounded text-sm";
      scriptBtn.onclick = (e) => e.stopPropagation();
      filmHeader.appendChild(scriptBtn);

      const filmBody = document.createElement("div");
      filmBody.id = filmToggleId;
      filmBody.className = "p-4 space-y-3";

      filmHeader.onclick = () => {
        const isHidden = filmBody.classList.toggle("hidden");
        filmHeader.querySelector(".chevron").textContent = isHidden ? "▸" : "▾";
      };

      const groupedByScene = {};
      const thumbnailTasks = film.shots.filter(s => s.shot_id === null);
      const realShots = film.shots.filter(s => s.shot_id !== null);

      for (const shot of realShots) {
        const key = shot.scene_number || "Unknown Scene";
        if (!groupedByScene[key]) groupedByScene[key] = [];
        if (!groupedByScene[key].some(s => s.shot_id === shot.shot_id)) {
          groupedByScene[key].push(shot);
        }
      }

      if (thumbnailTasks.length > 0) {
        groupedByScene["__thumbnails__"] = thumbnailTasks;
      }

      for (const [sceneNum, shots] of Object.entries(groupedByScene)) {
        const sceneToggleId = `${filmToggleId}-scene-${sceneNum}`;
        const isThumbnailSection = sceneNum === "__thumbnails__";

        const sceneSection = document.createElement("div");
        sceneSection.className = "bg-gray-900 rounded-lg overflow-hidden";

        const sceneHeader = document.createElement("div");
        sceneHeader.className = "flex items-center gap-2 cursor-pointer text-yellow-400 text-sm font-semibold px-4 py-2 bg-gray-700";
        sceneHeader.innerHTML = `
          <span class="chevron">▾</span>
          <span>${isThumbnailSection ? "Thumbnails & Storyboards" : `Scene ${sceneNum}`}</span>
        `;

        // Fixed-width tracks (not "1fr") so a scene with only 1-2 shots
        // doesn't stretch its boxes to fill the row -- same fixed card
        // size regardless of shot count, capped at 5 per row via max-width.
        const sceneBody = document.createElement("div");
        sceneBody.id = sceneToggleId;
        sceneBody.className = "grid gap-3 p-3";
        sceneBody.style.gridTemplateColumns = "repeat(auto-fill, 260px)";
        sceneBody.style.maxWidth = "calc(5 * 260px + 4 * 0.75rem)";

        sceneHeader.onclick = () => {
          const isHidden = sceneBody.classList.toggle("hidden");
          sceneHeader.querySelector(".chevron").textContent = isHidden ? "▸" : "▾";
        };

        shots.forEach(shot => {
          const visibleSteps = shot.steps.filter(step => step.status?.toLowerCase() !== "approved");
          const badge = computeShotBadge(shot.steps);

          const card = document.createElement("div");
          card.className = "bg-gray-800 rounded-lg p-3";
          card.innerHTML = `
            <div class="flex items-center justify-between mb-2">
              <span class="text-white font-bold text-sm">Shot ${shot.shot_number || "—"}</span>
              <span class="text-xs px-2 py-1 rounded ${badge.cls}">${badge.label}</span>
            </div>
          `;

          if (visibleSteps.length === 0) {
            const none = document.createElement("div");
            none.className = "text-xs text-gray-500";
            none.textContent = "Nothing left to do";
            card.appendChild(none);
          }

          visibleSteps.forEach(step => {
            // flex-wrap + a full-width label so a step's controls (dropdown,
            // due date, OPEN button) drop to their own line instead of
            // overflowing the fixed-width card and bleeding into the next
            // one -- there's more here than a single 260px row can fit.
            const stepRow = document.createElement("div");
            stepRow.className = "flex flex-wrap items-center gap-2 text-sm mt-1";

            if (step.scene_id !== undefined && step.scene_id !== null) {
              stepRow.setAttribute("data-scene-id", step.scene_id);
            }
            if (shot.shot_id !== undefined && shot.shot_id !== null && shot.shot_number !== "—") {
              stepRow.setAttribute("data-shot-id", shot.shot_id);
            }

            const label = document.createElement("span");
            label.className = "text-gray-300 w-full";
            label.textContent = step.step_name || `Step ${step.step_id}`;

            const due = document.createElement("span");
            due.className = "text-gray-500 text-xs";
            due.textContent = step.due_date || "--";

            stepRow.appendChild(label);
            stepRow.appendChild(buildShotStatusDropdown(shot, step));
            stepRow.appendChild(due);

            // Shot-level Layout/Animation OPEN -- only meaningful once the
            // gating condition is met (CapstoneLayout.py/CapstoneAnimation.py's
            // run_shot() enforce these server-side too; this just keeps the
            // button truthful about it instead of always showing enabled).
            // Layout -> Blocking -> Animation -> Lighting: each step's own
            // launcher action, gated on THIS SHOT's own prior step being
            // Approved or CUT (never scene-wide, never dependent on
            // sibling shots). Matches the identical gates
            // capstone_routes.py enforces server-side when Maya actually
            // opens each file (shot_blocking_context()/
            // shot_animation_context()/shot_lighting_context()). Blocking
            // Plus/Polish no longer exist as separate steps -- Blocking
            // and Animation are each their own top-level step now, not a
            // self-locked sub-step chain.
            const SHOT_OPEN_CONFIG = {
              "Layout": {
                action: "shot_layout",
                ready: shot.scene_layout_done,
                lockedTitle: "Not ready yet — scene Layout hasn't been approved"
              },
              "Blocking": {
                action: "shot_blocking",
                ready: shot.shot_layout_approved,
                lockedTitle: "Not ready yet — this shot's Layout hasn't been approved yet"
              },
              "Animation": {
                action: "shot_animation",
                ready: shot.shot_blocking_approved,
                lockedTitle: "Not ready yet — this shot's Blocking hasn't been approved yet"
              },
              "Lighting": {
                action: "shot_lighting",
                ready: shot.shot_animation_approved,
                lockedTitle: "Not ready yet — this shot's Animation hasn't been approved yet"
              }
            };
            const openConfig = SHOT_OPEN_CONFIG[step.step_name];
            if (openConfig && shot.shot_id) {
              const loginParam = encodeURIComponent(window.currentLoginName || "");
              if (openConfig.ready) {
                const openLink = document.createElement("a");
                openLink.href = `shottracker://open?action=${openConfig.action}&shot_id=${shot.shot_id}&login_name=${loginParam}`;
                openLink.className = "bg-blue-700 hover:bg-blue-600 text-white px-2 py-1 rounded text-xs";
                openLink.textContent = "OPEN";
                stepRow.appendChild(openLink);
              } else {
                const lockedSpan = document.createElement("span");
                lockedSpan.className = "bg-gray-700 text-gray-400 px-2 py-1 rounded text-xs cursor-not-allowed";
                lockedSpan.title = openConfig.lockedTitle;
                lockedSpan.textContent = "🔒 OPEN";
                stepRow.appendChild(lockedSpan);
              }
            }

            card.appendChild(stepRow);
          });

          sceneBody.appendChild(card);
        });

        sceneSection.appendChild(sceneHeader);
        sceneSection.appendChild(sceneBody);
        filmBody.appendChild(sceneSection);
      }

      filmSection.appendChild(filmHeader);
      filmSection.appendChild(filmBody);
      container.appendChild(filmSection);
    });
  } catch (err) {
    console.error("❌ Error loading film shots:", err);
  }
}



function sortShots(shots) {
  if (!Array.isArray(shots)) return [];
  const { field, direction } = filmShotsSort;
  return [...shots].sort((a, b) => {
    let valA = (a.steps?.[0]?.[field]) ?? a[field];
    let valB = (b.steps?.[0]?.[field]) ?? b[field];

    if (field.toLowerCase().includes("date")) {
      valA = valA ? new Date(valA).getTime() : 0;
      valB = valB ? new Date(valB).getTime() : 0;
    }

    if (valA < valB) return direction === "asc" ? -1 : 1;
    if (valA > valB) return direction === "asc" ? 1 : -1;
    return 0;
  });
}

function renderUserAssets() {
  const assetList = document.getElementById("todo-assets-list");
  if (!assetList) return;


  fetch("/dashboard/api/user_assets")
    .then(res => res.json())
    .then(assets => {
      if (!assets || assets.length === 0) {
        assetList.innerHTML = "<p class='text-gray-400 px-4 py-2'>No assets assigned.</p>";
        return;
      }

      // One row per asset, not one per MOD/TEX/RIG step -- same grouping
      // idea as the assignments widget (one card per assignment, not one
      // per Blocking/Blocking Plus/Polish). Within each asset's own rows
      // (this user's assigned steps for it), show whichever one is
      // is_active_step -- that's the step actually actionable right now.
      // If none of this user's own rows for this asset are active (e.g.
      // they only had Modeling and it's since moved on to someone else's
      // Texture/Surface), fall back to their first row so the asset still
      // shows up, just with OPEN correctly greyed out.
      //
      // Proxy is grouped SEPARATELY from the Modeling/Texture-Surface/
      // Rigging trio for the same asset -- it's not part of that
      // sequential progression (no lock/FB gate at all, see
      // migrate_add_proxy_step.py), so it shouldn't get collapsed away
      // just because Modeling happens to also be active right now. A
      // Character/Rigs asset the user is assigned on both fronts can
      // legitimately show two rows: one for Proxy, one for MOD/TEX/RIG.
      const grouped = new Map();
      for (const a of assets) {
        const key = a.step_name === "Proxy" ? `${a.asset_id}::proxy` : a.asset_id;
        if (!grouped.has(key)) grouped.set(key, []);
        grouped.get(key).push(a);
      }
      const representatives = Array.from(grouped.values()).map(
        group => group.find(a => a.is_active_step) || group[0]
      );

      assetList.innerHTML = `
      <table class="min-w-full text-white text-sm table-auto">
        <thead class="bg-slate-700 text-xs uppercase text-gray-300">
          <tr>
            <th class="px-4 py-2 text-left">Asset</th>
            <th class="px-4 py-2 text-left">Film</th>
            <th class="px-4 py-2 text-left">Step</th>
            <th class="px-4 py-2 text-left">Due Date</th>
            <th class="px-4 py-2 text-left">Status</th>
            <th class="px-4 py-2 text-left"></th>
          </tr>
        </thead>
        <tbody>
          ${representatives.map(a => {
        const due = a.due_date || "—";
            // 🧩 Sort step_nodes by Y value from their "position" string (e.g. "100 30")
            const nodeOptions = a.step_nodes
              .sort((x, y) => {
                const getY = (pos) => {
                  if (!pos) return 0;
                  const parts = pos.split(" ");
                  return parseFloat(parts[1]) || 0; // second number is Y
                };
                return getY(x.position) - getY(y.position);
              })
              .map(n => {
                const selected = n.node_id === a.node_id ? "selected" : "";
                return `<option value="${n.node_id}" style="background-color: ${n.color}" ${selected}>${n.name}</option>`;
              })
              .join("");



        return `
              <tr class="border-b border-slate-700 hover:bg-slate-700">
                <td class="px-4 py-2">
                  <div class="font-semibold">${a.name}</div>
                  <div class="text-xs text-gray-400">${a.category}</div>
                </td>
                <td class="px-4 py-2">${a.film_name}</td>
                <td class="px-4 py-2">${a.step_name}</td>
                <td class="px-4 py-2 text-sm">${due}</td>
                <td class="px-4 py-2">
                  <select
                      class="text-black text-sm px-2 py-1 rounded"
                      data-asset-id="${a.asset_id}"
                      data-step-id="${a.step_id}">
                    ${nodeOptions}
                  </select>
                </td>
                <td class="px-4 py-2">
                  ${(() => {
            const isProxy = a.step_name === "Proxy";
            // Proxy has no lock/FB gate at all -- always openable, and its
            // URI needs step_name=Proxy so Assets.py routes it to Proxy's
            // own independent lineage instead of the MOD/TEX/RIG gated flow.
            const canOpen = isProxy || a.is_active_step;
            const loginParam = encodeURIComponent(window.currentLoginName || "");
            const openUri = isProxy
              ? `shottracker://open?action=asset&asset_id=${a.asset_id}&step_name=Proxy&login_name=${loginParam}`
              : `shottracker://open?action=asset&asset_id=${a.asset_id}&login_name=${loginParam}`;

            // Unlocked/eligible but a mutual-exclusion sibling (e.g. Texture-
            // Surface, for a Rigging row) is currently open in Maya by
            // someone else -- surfaces that here so the artist finds out
            // BEFORE launching Maya, instead of only from Assets.py's
            // warning once it's already open. See checkout_blocked_by,
            // computed by _resolve_checkout_blockers() in dashboard_routes.py.
            if (canOpen && a.checkout_blocked_by) {
              return `<span class="bg-gray-700 text-gray-400 px-3 py-1 rounded text-sm inline-block cursor-not-allowed" title="${a.step_name} is currently open by ${a.checkout_blocked_by} — try again once they're done">🔒 OPEN</span>`;
            }

            return canOpen
              ? `<a href="${openUri}" class="bg-blue-700 hover:bg-blue-600 text-white px-3 py-1 rounded text-sm inline-block">OPEN</a>`
              : `<span class="bg-gray-700 text-gray-400 px-3 py-1 rounded text-sm inline-block cursor-not-allowed" title="Not ready yet — the prior step isn't done">🔒 OPEN</span>`;
          })()}
                </td>
              </tr>
            `;
      }).join("")}
        </tbody>
      </table>
    `;

      assetList.querySelectorAll("select[data-asset-id]").forEach(select => {
        // 🟡 Set initial color on load
        const selectedOption = select.options[select.selectedIndex];
        select.style.backgroundColor = selectedOption.style.backgroundColor || "#888";

        select.addEventListener("change", e => {
          const assetId = select.dataset.assetId;
          const stepId = select.dataset.stepId;
          const newNodeId = select.value;

          console.log("Sending update:", { asset_id: assetId, step_id: stepId, node_id: newNodeId });

          fetch("/dashboard/api/update_asset_status", {
            method: "POST",
            headers: {
              "Content-Type": "application/json"
            },
            body: JSON.stringify({
              asset_id: assetId,
              step_id: stepId,
              node_id: newNodeId
            })
          })
            .then(res => {
              if (!res.ok) throw new Error("Update failed");
              return res.json();
            })
            .then(() => {
              const selectedOption = select.options[select.selectedIndex];
              select.style.backgroundColor = selectedOption.style.backgroundColor || "#888";
            })
            .catch(err => {
              console.error("Error updating asset status:", err);
              alert("⚠️ Failed to update status.");
            });
        });
      });



    });
}

// --- Local UI update for thumbnails or skipped DB writes ---
function updateLocalStatus(taskId, stepId, newStatus) {
  const cell = document.querySelector(
    `[data-shot-id="${taskId}"] [data-step-id="${stepId}"]`
  );
  if (cell && cell.tagName === "SELECT") {
    const option = Array.from(cell.options).find(
      (opt) => opt.value === newStatus
    );
    if (option) cell.value = option.value;
    updateDropdownColor(cell);
    cell.classList.add("ring-2", "ring-green-500");
    setTimeout(() => cell.classList.remove("ring-2", "ring-green-500"), 800);
  }
}

