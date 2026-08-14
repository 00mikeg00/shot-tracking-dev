// classEditor.js - per-class Assignment Config editor
// Scoped to ONE class at a time (opened via the "Config" button on that
// class's row in classes.html) rather than the old whole-semester editor,
// which opened with an empty in-memory class list that had to be manually
// repopulated per class before Save -- saving after editing only one
// class silently dropped every other class from assignments_config.json.
console.log("✅ classEditor.js loaded");

let currentClassId = null;
let currentClassName = "";

let currentClassForNewAssignment = "";
let rigSelectContext = { assignmentName: '' };
let rigModalWorkingRigs = []; // rig paths for the open rig modal; duplicates allowed (same rig referenced multiple times)
let starterScenes = []; // full paths under this class's Assignments/StarterScenes folder, from the by-class GET

// ─────────────────────────────────────────────────────────────────────────────
// MODAL CONTROLS
// ─────────────────────────────────────────────────────────────────────────────

window.openClassConfigModal = async function (classId, className) {
  currentClassId = classId;
  currentClassName = className;
  currentClassForNewAssignment = className;

  const modal = document.getElementById('class-config-modal');
  if (!modal) return console.warn('Missing #class-config-modal');

  document.getElementById('class-config-title').textContent = `Assignment Config — ${className}`;
  modal.classList.remove('hidden');

  try {
    const res = await fetch(`/classes/assignment-config/by-class/${classId}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }
    const data = await res.json();

    classAssignments = data.assignments || {};
    rigList = data.rigs || [];
    starterScenes = data.starter_scenes || [];

    renderClassAssignments();
  } catch (err) {
    console.error("❌ Failed to load class config:", err);
    Swal.fire("Error", `Could not load config for '${className}': ${err.message}`, "error");
  }
};

window.closeClassConfigModal = function () {
  const modal = document.getElementById('class-config-modal');
  if (modal) modal.classList.add('hidden');
};

window.openNewAssignmentModal = async function () {
  try {
    const res = await fetch(`/classes/api/assignments/by-class/${encodeURIComponent(currentClassForNewAssignment)}`);
    const assignmentList = await res.json();

    const dropdown = document.getElementById('assignment-name-dropdown');
    dropdown.innerHTML = '<option value="">-- Select from existing --</option>' +
      assignmentList.map(name => `<option value="${name}">${name}</option>`).join('');

    document.getElementById('new-assignment-input').value = '';
    document.getElementById('new-assignment-modal').classList.remove('hidden');
  } catch (err) {
    console.error("❌ Failed to load assignments:", err);
    Swal.fire("Error loading assignments");
  }
};

window.closeNewAssignmentModal = function () {
  document.getElementById('new-assignment-modal').classList.add('hidden');
};

window.openRigModal = function (assignmentName) {
  rigSelectContext = { assignmentName };
  // Copy so edits while the modal is open (including across search filters) aren't lost.
  rigModalWorkingRigs = [...(classAssignments[assignmentName].rigs || [])];

  const container = document.getElementById('rig-options-container');
  const searchInput = document.getElementById('rig-search-input');

  function countOf(rig) {
    return rigModalWorkingRigs.filter(r => r === rig).length;
  }

  function renderFilteredRigs(filterText = "") {
    const filtered = rigList.filter(rig => rig.toLowerCase().includes(filterText.toLowerCase()));

    container.innerHTML = filtered.map(rig => {
      const file = rig.split(/[\\/]/).pop();
      return `
        <label class="flex items-center space-x-3 p-3 border rounded bg-gray-50 text-base w-full" title="${file}">
          <input type="number" min="0" value="${countOf(rig)}" data-rig="${rig}"
                 class="rig-count-input w-16 border rounded px-2 py-1 text-black" />
          <span class="truncate w-full">${file}</span>
        </label>
      `;
    }).join('');

    container.querySelectorAll('.rig-count-input').forEach(input => {
      input.addEventListener('change', () => {
        const rig = input.dataset.rig;
        const count = Math.max(0, parseInt(input.value, 10) || 0);
        input.value = count;
        rigModalWorkingRigs = rigModalWorkingRigs.filter(r => r !== rig);
        for (let i = 0; i < count; i++) rigModalWorkingRigs.push(rig);
      });
    });
  }

  // Initial render
  renderFilteredRigs();

  // Bind live search
  searchInput.addEventListener('input', e => {
    renderFilteredRigs(e.target.value);
  });

  document.getElementById('rig-modal').classList.remove('hidden');
};

window.closeRigModal = function () {
  document.getElementById('rig-modal').classList.add('hidden');
};

// ─────────────────────────────────────────────────────────────────────────────
// UI EVENT BINDINGS
// ─────────────────────────────────────────────────────────────────────────────

document.body.addEventListener("click", (e) => {
  const configBtn = e.target.closest(".config-class-btn");
  if (configBtn) {
    openClassConfigModal(parseInt(configBtn.dataset.classId, 10), configBtn.dataset.className);
    return;
  }

  if (e.target.id === "class-config-add-assignment-btn") {
    openNewAssignmentModal();
  }

  if (e.target.classList.contains("delete-assignment")) {
    const assignmentName = e.target.dataset.assignment;
    if (confirm(`Delete assignment '${assignmentName}'?`)) {
      delete classAssignments[assignmentName];
      renderClassAssignments();
    }
  }

  if (e.target.classList.contains("select-rigs-btn")) {
    const assignmentName = e.target.dataset.assignment;
    openRigModal(assignmentName);
  }
});

document.body.addEventListener("change", (e) => {
  if (e.target.classList.contains("camera-toggle")) {
    const assignmentName = e.target.dataset.assignment;
    if (!classAssignments[assignmentName]) return;
    classAssignments[assignmentName].camera = e.target.checked;
  }

  if (e.target.classList.contains("frame-start") || e.target.classList.contains("frame-end")) {
    const assignmentName = e.target.dataset.assignment;
    const field = e.target.classList.contains("frame-start") ? "frame_start" : "frame_end";
    const value = e.target.value === "" ? null : parseInt(e.target.value, 10);

    if (!classAssignments[assignmentName]) return;
    classAssignments[assignmentName][field] = Number.isNaN(value) ? null : value;
  }

  if (e.target.classList.contains("filename")) {
    const assignmentName = e.target.dataset.assignment;
    if (!classAssignments[assignmentName]) return;
    classAssignments[assignmentName].filename = e.target.value;
  }

  if (e.target.classList.contains("starter-scene-select")) {
    const assignmentName = e.target.dataset.assignment;
    if (!classAssignments[assignmentName]) return;
    classAssignments[assignmentName].starter_scene = e.target.value;
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// SAVE / SUBMIT LOGIC
// ─────────────────────────────────────────────────────────────────────────────

window.saveClassConfig = async function () {
  if (!currentClassId) return;

  const entries = {};
  for (const [assignmentName, cfg] of Object.entries(classAssignments)) {
    entries[assignmentName] = {
      filename: cfg.filename || "",
      camera: !!cfg.camera,
      rigs: (cfg.rigs || []).map(r => ({ path: r })),
      frame_start: cfg.frame_start ?? null,
      frame_end: cfg.frame_end ?? null,
      starter_scene: cfg.starter_scene || ""
    };
  }

  console.log("💾 Saving class config:", currentClassId, currentClassName);

  try {
    const result = await fetch(`/classes/assignment-config/save-class/${currentClassId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ assignments: entries })
    });

    const json = await result.json();
    if (json.success) {
      Swal.fire('✅ Config Saved', `Saved for ${currentClassName}${json.warning ? ` (${json.warning})` : ''}`, json.warning ? 'warning' : 'success');
      closeClassConfigModal();
    } else {
      Swal.fire('❌ Save Failed', json.error || 'Check server logs.', 'error');
    }
  } catch (err) {
    console.error("❌ Failed to save class config:", err);
    Swal.fire('❌ Save Failed', err.message, 'error');
  }
};

window.confirmNewAssignment = function () {
  const dropVal = document.getElementById('assignment-name-dropdown').value;
  const inputVal = document.getElementById('new-assignment-input').value.trim();
  const aName = inputVal || dropVal;

  if (!aName) {
    Swal.fire('Please enter or select an assignment name.');
    return;
  }

  classAssignments[aName] = {
    filename: aName,
    camera: false,
    rigs: [],
    frame_start: null,
    frame_end: null,
    starter_scene: ""
  };

  closeNewAssignmentModal();
  renderClassAssignments();
};

window.confirmRigSelection = function () {
  const selected = [...rigModalWorkingRigs];
  const { assignmentName } = rigSelectContext;
  classAssignments[assignmentName].rigs = selected;

  closeRigModal();
  renderClassAssignments(); // ✅ to update rig summary
};

// ─────────────────────────────────────────────────────────────────────────────
// RENDER
// ─────────────────────────────────────────────────────────────────────────────

function rigSummary(rigs) {
  const names = (rigs || []).map(r => {
    // normalize to string
    let rigPath = "";
    if (typeof r === "string") {
      rigPath = r;
    } else if (r && typeof r.path === "string") {
      rigPath = r.path;
    } else if (Array.isArray(r)) {
      rigPath = r[0] || "";  // handles nested array edge cases
    } else if (typeof r === "object" && Object.keys(r).length) {
      rigPath = Object.values(r)[0]; // last resort fallback
    }

    return typeof rigPath === "string" && rigPath.match(/[\\/]/)
      ? rigPath.split(/[\\/]/).pop()
      : "(Unknown)";
  });

  if (names.length === 0) return "None selected";

  // Same rig can be referenced multiple times (e.g. 3 balls in one scene) — show as "x3".
  const counts = {};
  names.forEach(n => { counts[n] = (counts[n] || 0) + 1; });
  return Object.entries(counts)
    .map(([n, c]) => c > 1 ? `${n} ×${c}` : n)
    .join(", ");
}

function renderClassAssignments() {
  const container = document.getElementById("class-config-container");
  if (!container) return;

  const entries = Object.entries(classAssignments);

  if (entries.length === 0) {
    container.innerHTML = `<p class="text-gray-400 py-4">No assignments configured yet — use "+ Add Assignment" below.</p>`;
    return;
  }

  container.innerHTML = entries.map(([aName, cfg]) => `
    <div class="mb-3 assignment-block border rounded p-2 bg-gray-50 text-black" data-assignment="${aName}">
      <div class="flex justify-between items-center">
          <strong>${aName}</strong>
          <button class="delete-assignment text-red-600" data-assignment="${aName}" title="Delete Assignment">🗑</button>
      </div>
      <div class="flex flex-col gap-2">
        <div class="flex gap-2 items-center flex-wrap">
          <label>Filename:</label>
          <input value="${cfg.filename || ''}" class="filename border px-2 py-1 rounded text-black bg-white" data-assignment="${aName}">
          <label><input type="checkbox" class="camera-toggle" ${cfg.camera ? 'checked' : ''} data-assignment="${aName}"> Camera</label>
          <label>Frame Start:</label>
          <input type="number" value="${cfg.frame_start ?? ''}" class="frame-start border px-2 py-1 rounded text-black bg-white w-20" data-assignment="${aName}">
          <label>Frame End:</label>
          <input type="number" value="${cfg.frame_end ?? ''}" class="frame-end border px-2 py-1 rounded text-black bg-white w-20" data-assignment="${aName}">
        </div>
        <label class="font-medium">Rigs:</label>
          <button class="select-rigs-btn text-sm text-black bg-gray-200 px-3 py-1 rounded" data-assignment="${aName}">
            Select Rigs
          </button>
          <div class="rig-list-summary text-xs text-blue-400 mt-1">
            ${rigSummary(cfg.rigs)}
          </div>
        <label class="font-medium">Starter Scene:</label>
        <select class="starter-scene-select border px-2 py-1 rounded text-black bg-white" data-assignment="${aName}">
          <option value="">-- None (blank scene) --</option>
          ${starterScenes.map(path => `<option value="${path}" ${cfg.starter_scene === path ? 'selected' : ''}>${path.split(/[\\/]/).pop()}</option>`).join('')}
        </select>
        ${starterScenes.length === 0 ? `<p class="text-xs text-gray-500">No starter scenes found for this class's StarterScenes folder.</p>` : ''}
      </div>
    </div>
  `).join('');
}
