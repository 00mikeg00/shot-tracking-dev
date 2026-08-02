// classEditor.js - MODAL ENHANCEMENTS
console.log("✅ classEditor.js loaded");

let currentSemesterId = null;

let currentClassForNewAssignment = "";
let rigSelectContext = { className: '', assignmentName: '' };
let rigModalWorkingRigs = []; // rig paths for the open rig modal; duplicates allowed (same rig referenced multiple times)
let collapsedClasses = new Set(); // class names the user has collapsed; survives renderClasses() rebuilds
// ─────────────────────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  // Ensure these two variables are globally available or injected before this file runs
  renderClasses(assignmentsData, rigList);




  // ─────────────────────────────────────────────────────────────────────────────
  // MODAL CONTROLS
  // ─────────────────────────────────────────────────────────────────────────────

  window.openSemesterConfigModal = function () {
    const modal = document.getElementById('semester-config-modal');
    if (!modal) return console.warn('Missing #semester-config-modal');
    modal.classList.remove('hidden');

    console.log("📡 Fetching semesters...");

    fetch('/semesters')
      .then(res => res.json())
      .then(semesters => {
        console.log("📚 Semesters received:", semesters);

        const select = document.getElementById('semester-select');

        // Pick the current semester if one is marked, otherwise use the first
        const current = semesters.find(s => s.current) || semesters[0];
        console.log("🎯 Current semester:", current);

        select.innerHTML = semesters.map(s =>
          `<option value="${s.id}" ${s.current ? 'selected' : ''}>
          ${s.year}-${s.term}
        </option>`
        ).join('');

        // ✅ Store current ID globally
        currentSemesterId = current.id;
        console.log("🎯 currentSemesterId set to:", currentSemesterId);

        console.log("✅ Semester select values:",
          Array.from(select.options).map(o => ({ text: o.text, value: o.value }))
        );

        // Watch for manual changes
        select.onchange = () => {
          currentSemesterId = parseInt(select.value, 10);
          console.log("🔄 Semester changed:", currentSemesterId);
        };

        console.log("📦 Fetching rigs...");
        fetch('/classes/api/rigs')
          .then(res => res.json())
          .then(rigs => {
            rigList = rigs;
            console.log("🔧 Rigs loaded:", rigList.length);

            assignmentsData = {};
            renderClasses(assignmentsData, rigList);

            const loadOldBtn = document.getElementById('load-old-btn');
            if (loadOldBtn) {
              loadOldBtn.addEventListener('click', loadOldConfig);
            }
          })
          .catch(err => {
            console.error("❌ Failed to fetch rigs:", err);
          });
      })
      .catch(err => {
        console.error("❌ Failed to load semesters:", err);
        Swal.fire("Error", "Could not load semester list from server.", "error");
      });
  };




  window.closeSemesterConfigModal = function () {
    const modal = document.getElementById('semester-config-modal');
    if (modal) modal.classList.add('hidden');
  }

  window.openNewClassModal = async function () {
    try {
      const res = await fetch('/classes/api/classes/names');
      const classNames = await res.json();

      const dropdown = document.getElementById('existing-class-dropdown');
      dropdown.innerHTML = '<option value="">-- Select a Class --</option>' +
        classNames.map(name => `<option value="${name}">${name}</option>`).join('');

      document.getElementById('new-class-input').value = '';
      document.getElementById('new-class-modal').classList.remove('hidden');
    } catch (err) {
      console.error("❌ Failed to load class list:", err);
      Swal.fire("Error loading classes");
    }
  }

  window.closeNewClassModal = function () {
    document.getElementById('new-class-modal').classList.add('hidden');
  }

  window.openNewAssignmentModal = async function (className) {
    currentClassForNewAssignment = className;

    try {
      const res = await fetch(`/classes/api/assignments/by-class/${encodeURIComponent(className)}`);
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
  }

  window.closeNewAssignmentModal = function () {
    document.getElementById('new-assignment-modal').classList.add('hidden');
  }

  window.openRigModal = function (className, assignmentName) {
    rigSelectContext = { className, assignmentName };
    // Copy so edits while the modal is open (including across search filters) aren't lost.
    rigModalWorkingRigs = [...(assignmentsData[className][assignmentName].rigs || [])];

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
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // UI EVENT BINDINGS
  // ─────────────────────────────────────────────────────────────────────────────

  document.body.addEventListener("click", (e) => {
    const modalBtn = e.target.closest("#open-config-modal");
    if (modalBtn) {
      openSemesterConfigModal();
      return;
    }

    if (e.target.id === "add-class-btn") {
      openNewClassModal(); // ✅ use modal instead of prompt
    }


    if (e.target.classList.contains("delete-class")) {
      const className = e.target.dataset.class;
      if (confirm(`Delete class '${className}'?`)) {
        delete assignmentsData[className];
        renderClasses(assignmentsData, rigList);
      }
    }

    if (e.target.classList.contains("delete-assignment")) {
      const { class: c, assignment: a } = e.target.dataset;
      if (confirm(`Delete assignment '${a}'?`)) {
        delete assignmentsData[c][a];
        renderClasses(assignmentsData, rigList);
      }
    }

    if (e.target.classList.contains("add-assignment-btn")) {
      const className = e.target.dataset.class;
      openNewAssignmentModal(className); // ✅ use new modal
    }

    if (e.target.classList.contains("select-rigs-btn")) {
      const className = e.target.dataset.class;
      const assignmentName = e.target.dataset.assignment;
      openRigModal(className, assignmentName);
    }

  });

  document.body.addEventListener("change", (e) => {
    if (e.target.classList.contains("camera-toggle")) {
      const className = e.target.dataset.class;
      const assignmentName = e.target.dataset.assignment;
      const checked = e.target.checked;

      if (!assignmentsData[className]) return;
      if (!assignmentsData[className][assignmentName]) return;

      assignmentsData[className][assignmentName].camera = checked;
    }

    if (e.target.classList.contains("frame-start") || e.target.classList.contains("frame-end")) {
      const className = e.target.dataset.class;
      const assignmentName = e.target.dataset.assignment;
      const field = e.target.classList.contains("frame-start") ? "frame_start" : "frame_end";
      const value = e.target.value === "" ? null : parseInt(e.target.value, 10);

      if (!assignmentsData[className]) return;
      if (!assignmentsData[className][assignmentName]) return;

      assignmentsData[className][assignmentName][field] = Number.isNaN(value) ? null : value;
    }
  });

  // Filter table rows based on search input
  document.getElementById('classSearchInput').addEventListener('input', function () {
    const filter = this.value.toLowerCase();
    document.querySelectorAll('#classTableBody tr').forEach(row => {
      const className = row.cells[1]?.textContent.toLowerCase() || '';
      row.style.display = className.includes(filter) ? '' : 'none';
    });
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // FETCH / LOAD DATA
  // ─────────────────────────────────────────────────────────────────────────────

  async function loadOldConfig() {
    const res = await fetch("/classes/assignment-config/files");
    const data = await res.json();
    const files = data.files || [];

    if (files.length === 0) {
      Swal.fire("No saved config files found.");
      return;
    }

    const list = files.map((f, i) =>
      `<button class="file-load-btn block px-4 py-2 text-left hover:bg-slate-800 w-full"
               data-path="${f.path}" id="file-${i}">
        ${f.name}
      </button>`
    ).join("");

    Swal.fire({
      title: "Select a config file",
      html: `<div class="text-left">${list}</div>`,
      showConfirmButton: false,
      didOpen: () => {
        document.querySelectorAll(".file-load-btn").forEach(btn => {
          btn.addEventListener("click", () => {
            const path = btn.getAttribute("data-path");
            loadAssignmentConfigFromFile(path);
          });
        });
      }
    });
  }
  
  
  function loadAssignmentConfigFromFile(filePath) {
    fetch(filePath)
      .then(res => res.json())
      .then(parsed => {
        if (!parsed.semester) {
          Swal.fire("❌ Invalid File", "Missing 'semester' field.", "error");
          return;
        }

        console.log("📥 Loaded old config:", parsed);

        const select = document.getElementById("semester-select");
        if (select && parsed.semester.name) {
          const match = Array.from(select.options).find(
            opt => opt.textContent === parsed.semester.name
          );
          if (match) {
            select.value = match.value;
            currentSemesterId = parseInt(match.value, 10);
          } else {
            // If the semester doesn't exist in dropdown, create it (for display only)
            const opt = document.createElement("option");
            opt.textContent = parsed.semester.name;
            // 🔧 use a temporary fake ID instead of name
            opt.value = "-1";
            select.appendChild(opt);
            select.value = opt.value;
            currentSemesterId = -1;
          }
        }

        // 2️⃣ Build assignmentsData
        const semesterData = parsed.semester.classes || parsed.semester;
        const next = {};

        for (const [className, assignments] of Object.entries(semesterData)) {
          if (className === "name" || className === "semesterName") continue;
          next[className] = {};

          for (const [assignmentName, cfg] of Object.entries(assignments)) {
            const rigs = (cfg.rigs || []).map(r => {
              if (typeof r === "string") return r;
              let p = r;
              while (p && typeof p === "object" && "path" in p) p = p.path;
              return typeof p === "string" ? p : "";
            }).filter(Boolean);

            next[className][assignmentName] = {
              filename: cfg.filename || "",
              camera: !!cfg.camera,
              rigs,
              frame_start: cfg.frame_start ?? null,
              frame_end: cfg.frame_end ?? null
            };
          }
        }

        assignmentsData = next;
        assignmentsData.semesterName = parsed.semester.name || "";

        renderClasses(assignmentsData, rigList);
        Swal.fire("✅ Config Loaded", "You're now editing the saved config.", "success");
      })
      .catch(err => {
        console.error("❌ Failed to load config:", err);
        Swal.fire("Load Failed", "Could not read file.", "error");
      });
  }



  

  async function loadSemesterData(semesterId) {
    const res = await fetch(`/api/assignment-config/by-semester/${semesterId}`);
    const data = await res.json();
    const container = document.getElementById('semester-config-body');
    container.innerHTML = Object.entries(data.classes).map(([className, assignments]) => {
      return `
        <div class="border-t pt-4">
          <h3 class="text-lg font-semibold mb-2">${className}</h3>
          ${Object.entries(assignments).map(([aName, cfg]) => `
            <div class="mb-3">
              <strong>${aName}</strong>
              <div class="flex flex-col gap-2">
                <div class="flex gap-2 items-center flex-wrap">
                  <label>Filename:</label>
                  <input value="${cfg.filename}" class="filename border px-2 py-1 rounded text-white bg-white" data-class="${className}" data-assignment="${aName}">
                  <label><input type="checkbox" class="camera-toggle" ${cfg.camera ? 'checked' : ''} data-class="${className}" data-assignment="${aName}"> Camera</label>
                </div>

                <label class="font-medium text-white">Rigs:</label> <!-- ✅ Moved label above -->
                <select multiple class="rig-select border p-1 rounded w-full text-black bg-white" data-class="${className}" data-assignment="${aName}">
                  ${data.rigs.map(rigPath => {
        const selected = cfg.rigs.includes(rigPath) ? 'selected' : '';
        const filename = rigPath.split(/[\\/]/).pop();
        return `<option value="${rigPath}" ${selected}>${filename}</option>`;
      }).join('')}
                </select>
              </div>
            </div>
          `).join('')}
        </div>
      `;
    }).join('');
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // SAVE / SUBMIT LOGIC
  // ─────────────────────────────────────────────────────────────────────────────

  window.saveSemesterConfig = async function () {
    const semesterSelect = document.getElementById('semester-select');
    const semesterId = currentSemesterId || parseInt(semesterSelect?.value, 10);

    if (!semesterId || isNaN(semesterId)) {
      Swal.fire("❌ Save Failed",
        `Invalid semester ID. Value received: ${semesterSelect?.value || '(none)'}`,
        "error");
      console.warn("⚠️ Semester ID invalid:", semesterSelect?.value);
      return;
    }


    const semesterName =
      semesterSelect?.options[semesterSelect.selectedIndex]?.text ||
      assignmentsData.semesterName ||
      "Unknown";

    const entries = {};
    for (const [className, assignments] of Object.entries(assignmentsData)) {
      if (className === "semesterName") continue;
      for (const [assignmentName, config] of Object.entries(assignments)) {
        entries[className] ??= {};
        entries[className][assignmentName] = {
          filename: config.filename || "",
          camera: !!config.camera,
          rigs: (config.rigs || []).map(r => ({ path: r })),
          frame_start: config.frame_start ?? null,
          frame_end: config.frame_end ?? null
        };
      }
    }

    console.log("💾 Saving semester config:", semesterId, semesterName);

    const result = await fetch(`/classes/assignment-config/save-semester/${semesterId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ classes: entries })
    });

    const json = await result.json();
    if (json.success) {
      Swal.fire('✅ Config Saved', `Saved for ${semesterName}`, 'success');
      closeSemesterConfigModal();
    } else {
      Swal.fire('❌ Save Failed', json.error || 'Check server logs.', 'error');
    }
  };


  window.saveDraftConfig = async function () {
    const semesterSelect = document.getElementById('semester-select');
    const semesterName = semesterSelect.options[semesterSelect.selectedIndex].text;

    const entries = {};

    for (const [className, assignments] of Object.entries(assignmentsData)) {
      for (const [assignmentName, config] of Object.entries(assignments)) {
        entries[className] ??= {};
        entries[className][assignmentName] = {
          filename: config.filename || '',
          camera: !!config.camera,
          rigs: (config.rigs || []).map(r => ({ path: r })),
          frame_start: config.frame_start ?? null,
          frame_end: config.frame_end ?? null
        };
      }
    }

    const result = await fetch(`/classes/api/assignment-config/save-draft`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ semester: { name: semesterName, ...entries } })
    });

    const json = await result.json();
    if (json.success) {
      Swal.fire('📄 Draft Saved', 'Progress saved safely.', 'info');
    } else {
      Swal.fire('❌ Draft Failed', json.error || 'Check server logs.', 'error');
    }
  }

  window.confirmNewClass = function () {
    const newClassName = document.getElementById("new-class-input").value.trim();
    const selectedExisting = document.getElementById("existing-class-dropdown").value;
    const includeAssignments = document.getElementById("include-assignments-checkbox").checked;

    const className = newClassName || selectedExisting;
    if (!className) {
      Swal.fire({ icon: 'warning', text: "Select or enter a class name." });
      return;
    }

    if (assignmentsData[className]) {
      Swal.fire({ icon: 'error', text: "This class already exists." });
      return;
    }

    // 🧠 If checkbox is selected: Fetch assignments from backend
    if (includeAssignments) {
      fetch(`/classes/api/assignments/by-class/${encodeURIComponent(className)}`)
        .then(res => res.json())
        .then(assignments => {
          assignmentsData[className] = {};
          assignments.forEach(name => {
            assignmentsData[className][name] = {
              filename: name,
              camera: false,
              rigs: [],
              frame_start: null,
              frame_end: null
            };
          });
          closeNewClassModal();
          renderClasses(assignmentsData, rigList);
        })
        .catch(() => {
          Swal.fire({ icon: 'error', text: "Failed to load assignments." });
        });
    } else {
      assignmentsData[className] = {};
      closeNewClassModal();
      renderClasses(assignmentsData, rigList);
    }
  }
  

  window.confirmNewAssignment = function () {
    const dropVal = document.getElementById('assignment-name-dropdown').value;
    const inputVal = document.getElementById('new-assignment-input').value.trim();
    const aName = inputVal || dropVal;

    if (!aName) {
      Swal.fire('Please enter or select an assignment name.');
      return;
    }

    if (!assignmentsData[currentClassForNewAssignment]) {
      assignmentsData[currentClassForNewAssignment] = {};
    }

    assignmentsData[currentClassForNewAssignment][aName] = {
      filename: aName,
      camera: false,
      rigs: [],
      frame_start: null,
      frame_end: null
    };

    closeNewAssignmentModal();
    renderClasses(assignmentsData, rigList);
  }

  window.confirmRigSelection = function () {
    const selected = [...rigModalWorkingRigs];

    const { className, assignmentName } = rigSelectContext;
    assignmentsData[className][assignmentName].rigs = selected;

    closeRigModal();
    renderClasses(assignmentsData, rigList);  // ✅ to update rig summary
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // HELPERS / UTILITIES
  // ─────────────────────────────────────────────────────────────────────────────

  function renderClasses(assignmentsData, rigList) {
    const container = document.getElementById("class-container");
    if (!container) return;

    // ✅ Filter out helper or non-class keys
    const validClasses = Object.entries(assignmentsData).filter(
      ([className]) => className !== "semesterName" && className !== "name"
    );

    container.innerHTML = validClasses
      .map(([className, assignments]) => {
        const assignmentsHTML = Object.entries(assignments)
          .map(([aName, cfg]) => `
        <div class="mb-3 assignment-block border rounded p-2 bg-gray-50 text-black" data-assignment="${aName}" draggable="true">
          <div class="flex justify-between items-center">
              <strong>${aName}</strong>
              <div class="flex gap-2 items-center">
                  <button class="delete-assignment text-red-600" data-class="${className}" data-assignment="${aName}" title="Delete Assignment">🗑</button>
                  <div class="drag-handle text-gray-400 cursor-move" title="Reorder Assignment">⠿</div>
              </div>
          </div>  
          <div class="flex flex-col gap-2">
            <div class="flex gap-2 items-center flex-wrap">
              <label>Filename:</label>
              <input value="${cfg.filename || ''}" class="filename border px-2 py-1 rounded text-black bg-white" data-class="${className}" data-assignment="${aName}">
              <label><input type="checkbox" class="camera-toggle" ${cfg.camera ? 'checked' : ''} data-class="${className}" data-assignment="${aName}"> Camera</label>
              <label>Frame Start:</label>
              <input type="number" value="${cfg.frame_start ?? ''}" class="frame-start border px-2 py-1 rounded text-black bg-white w-20" data-class="${className}" data-assignment="${aName}">
              <label>Frame End:</label>
              <input type="number" value="${cfg.frame_end ?? ''}" class="frame-end border px-2 py-1 rounded text-black bg-white w-20" data-class="${className}" data-assignment="${aName}">
            </div>
            <label class="font-medium">Rigs:</label>
              <button class="select-rigs-btn text-sm text-black bg-gray-200 px-3 py-1 rounded"
                      data-class="${className}" data-assignment="${aName}">
                Select Rigs
              </button>
              <div class="rig-list-summary text-xs text-blue-400 mt-1">
                ${(() => {
                  const names = (cfg.rigs || []).map(r => {
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

                    // only split if it's really a string
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
                })()}
              </div>
          </div>
        </div>`).join('');

        return `
        <div class="class-block border-t pt-4" data-class="${className}">
          <div class="flex justify-between items-center bg-red-800 px-4 py-2 rounded-t cursor-pointer"
               onclick="toggleConfigClass(this)">
            <h3 class="text-lg font-semibold text-white">${className}</h3>
            <div class="flex gap-3 items-center">
              <button class="delete-class-btn bg-red-600 text-white text-sm px-2 py-1 rounded hover:bg-red-700"
                      data-class="${className}">
                Delete Class
              </button>
              <span class="text-white text-xl font-bold">−</span>
            </div>
          </div>
          <div class="class-content px-2 pt-3 bg-slate-900 rounded-b">
            ${assignmentsHTML}
            <button class="add-assignment-btn mt-2 bg-green-600 text-white px-3 py-1 rounded" data-class="${className}">+ Add Assignment</button>
          </div>
        </div>`;
      })
      .join('');

    // Reapply any collapsed state that survived this rebuild
    container.querySelectorAll(".class-block").forEach(block => {
      const className = block.dataset.class;
      if (!collapsedClasses.has(className)) return;
      const header = block.firstElementChild;
      const content = header?.nextElementSibling;
      const icon = header?.querySelector("span");
      if (content) content.style.display = "none";
      if (icon) icon.textContent = "+";
    });

    enableDragSort();

    // ✅ Bind delete-class buttons
    document.querySelectorAll(".delete-class-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation(); // prevent collapse toggle
        const className = btn.dataset.class;
        Swal.fire({
          title: `Delete "${className}"?`,
          text: "This will remove the class and all its assignments from the config.",
          icon: "warning",
          showCancelButton: true,
          confirmButtonText: "Yes, delete",
          cancelButtonText: "Cancel"
        }).then((result) => {
          if (result.isConfirmed) {
            delete assignmentsData[className];
            renderClasses(assignmentsData, rigList);
          }
        });
      });
    });
  }

  
  
  window.toggleConfigClass = function (headerEl) {
    const content = headerEl.nextElementSibling;
    const icon = headerEl.querySelector("span");
    const className = headerEl.closest(".class-block")?.dataset.class;

    const isHidden = content.style.display === "none";
    content.style.display = isHidden ? "block" : "none";
    icon.textContent = isHidden ? "−" : "+";

    if (className) {
      if (isHidden) collapsedClasses.delete(className);
      else collapsedClasses.add(className);
    }
  };
  

  function gatherSemesterData() {
    const semesterSelect = document.getElementById('semester-select');
    const semesterName = semesterSelect.options[semesterSelect.selectedIndex].text;

    const data = { name: semesterName };

    for (const [className, assignments] of Object.entries(assignmentsData)) {
      data[className] = {};

      for (const [assignmentName, cfg] of Object.entries(assignments)) {
        data[className][assignmentName] = {
          filename: cfg.filename,
          camera: cfg.camera,
          rigs: (cfg.rigs || []).map(r => ({ path: r }))
        };
      }
    }

    return data;
  }

  function enableDragSort() {
    const container = document.getElementById("class-container");

    // CLASS DRAG SORTING
    container.querySelectorAll(".class-block").forEach((block) => {
      block.draggable = true;
      block.addEventListener("dragstart", (e) => { dragged = block; });
      block.addEventListener("dragover", (e) => { /* existing class drag code */ });
    });

    // ASSIGNMENT DRAG SORTING
    container.querySelectorAll(".class-block").forEach((block) => {
      const className = block.dataset.class;

      let draggedItem;

      block.querySelectorAll(".assignment-block").forEach(item => {
        item.draggable = true;

        item.addEventListener("dragstart", () => {
          draggedItem = item;
          item.classList.add("dragging");
        });

        item.addEventListener("dragend", () => {
          item.classList.remove("dragging");

          const order = Array.from(block.querySelectorAll(".assignment-block"))
            .map(el => el.dataset.assignment);

          const reordered = {};
          for (const key of order) {
            reordered[key] = assignmentsData[className][key];
          }

          assignmentsData[className] = reordered;
          renderClasses(assignmentsData, rigList);
        });

        item.addEventListener("dragover", (e) => {
          e.preventDefault();
          const after = getDragAfterElement(block, e.clientY);
          if (!after) {
            block.appendChild(draggedItem);
          } else {
            block.insertBefore(draggedItem, after);
          }
        });
      });
    });
  }

  function getDragAfterElement(container, y) {
    const draggableElements = [...container.querySelectorAll('.assignment-block:not(.dragging)')];

    return draggableElements.reduce((closest, child) => {
      const box = child.getBoundingClientRect();
      const offset = y - box.top - box.height / 2;

      if (offset < 0 && offset > closest.offset) {
        return { offset, element: child };
      } else {
        return closest;
      }
    }, { offset: Number.NEGATIVE_INFINITY }).element;
  }

  window.toggleSelectAll = function (selectAllCheckbox) {
    const checkboxes = document.querySelectorAll('input[name="class_ids"]');
    checkboxes.forEach(checkbox => checkbox.checked = selectAllCheckbox.checked);
  }


  // ─────────────────────────────────────────────────────────────────────────────
  // OTHER (CONTEXT-SPECIFIC)
  // ─────────────────────────────────────────────────────────────────────────────

  document.querySelectorAll('.rig-list-summary').forEach(summary => {
    const c = summary.closest('.class-block').dataset.class;
    const a = summary.closest('.assignment-block').dataset.assignment;

    const text = summary.innerText;
    const rigNames = text.split(',').map(t => t.trim()).filter(Boolean);

    const fullPaths = rigList.filter(path => rigNames.includes(path.split(/[\\/]/).pop()));

    entries[c] ??= {};
    entries[c][a] ??= {};
    entries[c][a].rigs = fullPaths.map(r => ({ path: r }));
  });

});