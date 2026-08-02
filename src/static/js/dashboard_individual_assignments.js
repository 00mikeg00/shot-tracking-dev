  document.addEventListener("change", async (e) => {
    const fileInput = e.target;
    if (!fileInput.matches(".assignment-upload")) return;

    const form = fileInput.closest("form");
    const file = fileInput.files[0];
    if (!file) return;

    const assignmentId = form.dataset.assignmentId;
    const assignmentName = form.dataset.assignmentName;
    const className = form.dataset.className;

    const formData = new FormData();
    formData.append("file", file);
    formData.append("assignment_id", assignmentId);
    formData.append("assignment_name", assignmentName);
    formData.append("class_name", className);

    try {
      const res = await fetch("/review/upload_assignment", {
        method: "POST",
        body: formData
      });

      const result = await res.json();

      if (res.ok) {
        await Swal.fire({
          icon: "success",
          title: "Uploaded!",
          text: `${result.file_name} has been uploaded and submitted.`,
          timer: 2000,
          showConfirmButton: false
        });

        fetchUserAssignmentsForSemester(); // 🔁 Refresh dashboard after upload
      } else {
        Swal.fire("Error", result.error || "Upload failed", "error");
      }
    } catch (err) {
      console.error("Upload error:", err);
      Swal.fire("Upload Error", "See console for details", "error");
    }
  });

  // ---------------------------------------------------------------------
  // Planning drawings (Planning step) — multi-file upload, drag-drop or
  // file picker, tied to the logged-in Shot Tracker session (server-side
  // owner check), not the shared OS login.
  // ---------------------------------------------------------------------

  async function uploadPlanningDrawings(individualAssignmentId, fileList) {
    const files = Array.from(fileList || []).filter(f =>
      /\.(png|jpe?g)$/i.test(f.name)
    );
    if (files.length === 0) {
      Swal.fire("No valid files", "Only PNG/JPG images are accepted.", "warning");
      return;
    }

    const formData = new FormData();
    formData.append("individual_assignment_id", individualAssignmentId);
    files.forEach(f => formData.append("files", f));

    try {
      const res = await fetch("/planning/upload_drawings", {
        method: "POST",
        body: formData
      });
      const result = await res.json();

      if (res.ok) {
        await Swal.fire({
          icon: "success",
          title: "Uploaded!",
          text: `${result.files.length} drawing(s) uploaded.`,
          timer: 1500,
          showConfirmButton: false
        });
        loadPlanningDrawings(individualAssignmentId, `planning-list-${individualAssignmentId}`);
      } else {
        Swal.fire("Error", result.error || "Upload failed", "error");
      }
    } catch (err) {
      console.error("Planning upload error:", err);
      Swal.fire("Upload Error", "See console for details", "error");
    }
  }

  async function loadPlanningDrawings(individualAssignmentId, listElId) {
    const listEl = document.getElementById(listElId);
    if (!listEl) return;

    try {
      const res = await fetch(`/planning/list/${individualAssignmentId}`);
      if (!res.ok) return;
      const data = await res.json();
      const files = data.files || [];

      if (files.length === 0) {
        listEl.innerHTML = "";
        return;
      }

      listEl.innerHTML = files.map(f => `
        <div class="flex items-center justify-between gap-2 py-0.5">
          <span class="truncate" title="${f.file_name}">
            📄 ${f.file_name}${f.is_reviewed ? " <span class=\"text-green-400\">(reviewed)</span>" : ""}
          </span>
          <button type="button"
                  class="planning-drawing-delete text-red-400 hover:text-red-300 shrink-0"
                  data-drawing-id="${f.id}"
                  data-assignment-id="${individualAssignmentId}"
                  title="Delete this drawing">✕</button>
        </div>
      `).join("");
    } catch (err) {
      console.warn("Could not load planning drawings:", err);
    }
  }

  document.addEventListener("click", async (e) => {
    const btn = e.target.closest && e.target.closest(".planning-drawing-delete");
    if (!btn) return;

    const drawingId = btn.dataset.drawingId;
    const assignmentId = btn.dataset.assignmentId;

    const result = await Swal.fire({
      title: "Delete this drawing?",
      text: "This can't be undone.",
      icon: "warning",
      showCancelButton: true,
      confirmButtonColor: "#d33",
      confirmButtonText: "Yes, delete it"
    });
    if (!result.isConfirmed) return;

    try {
      const res = await fetch(`/planning/drawings/${drawingId}`, { method: "DELETE" });
      const data = await res.json();
      if (res.ok) {
        loadPlanningDrawings(assignmentId, `planning-list-${assignmentId}`);
      } else {
        Swal.fire("Error", data.error || "Delete failed", "error");
      }
    } catch (err) {
      console.error("Delete drawing error:", err);
      Swal.fire("Error", "See console for details", "error");
    }
  });

  // File picker
  document.addEventListener("change", async (e) => {
    const input = e.target;
    if (!input.matches(".planning-drawings-upload")) return;
    const assignmentId = input.dataset.assignmentId;
    if (input.files && input.files.length > 0) {
      await uploadPlanningDrawings(assignmentId, input.files);
      input.value = "";
    }
  });

  // Drag-and-drop
  document.addEventListener("dragover", (e) => {
    const zone = e.target.closest && e.target.closest(".planning-dropzone");
    if (!zone) return;
    e.preventDefault();
    zone.classList.add("border-blue-400", "bg-gray-700");
  });

  document.addEventListener("dragleave", (e) => {
    const zone = e.target.closest && e.target.closest(".planning-dropzone");
    if (!zone) return;
    zone.classList.remove("border-blue-400", "bg-gray-700");
  });

  document.addEventListener("drop", async (e) => {
    const zone = e.target.closest && e.target.closest(".planning-dropzone");
    if (!zone) return;
    e.preventDefault();
    zone.classList.remove("border-blue-400", "bg-gray-700");

    const assignmentId = zone.dataset.assignmentId;
    const dropped = e.dataTransfer && e.dataTransfer.files;
    if (dropped && dropped.length > 0) {
      await uploadPlanningDrawings(assignmentId, dropped);
    }
  });

  // ---------------------------------------------------------------------
  // Video reference (Planning step) — upload one clip at a time (server
  // transcodes it synchronously, so this can take a while) or add a link
  // to something found elsewhere.
  // ---------------------------------------------------------------------

  async function uploadVideoReference(individualAssignmentId, file, zoneEl) {
    const formData = new FormData();
    formData.append("individual_assignment_id", individualAssignmentId);
    formData.append("file", file);

    const originalText = zoneEl ? zoneEl.textContent : "";
    if (zoneEl) {
      zoneEl.textContent = "⏳ Converting... this can take a minute for longer clips";
      zoneEl.classList.add("pointer-events-none", "opacity-60");
    }

    try {
      const res = await fetch("/video_reference/upload", {
        method: "POST",
        body: formData
      });
      const result = await res.json();

      if (res.ok) {
        await Swal.fire({
          icon: "success",
          title: "Uploaded!",
          text: "Reference video converted and saved.",
          timer: 1500,
          showConfirmButton: false
        });
        loadVideoReferences(individualAssignmentId, `videoref-list-${individualAssignmentId}`);
      } else {
        Swal.fire("Error", result.error || "Upload failed", "error");
      }
    } catch (err) {
      console.error("Video reference upload error:", err);
      Swal.fire("Upload Error", "See console for details", "error");
    } finally {
      if (zoneEl) {
        zoneEl.textContent = originalText;
        zoneEl.classList.remove("pointer-events-none", "opacity-60");
      }
    }
  }

  async function addVideoReferenceLink(individualAssignmentId, url) {
    try {
      const res = await fetch("/video_reference/link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ individual_assignment_id: individualAssignmentId, url })
      });
      const result = await res.json();

      if (res.ok) {
        loadVideoReferences(individualAssignmentId, `videoref-list-${individualAssignmentId}`);
      } else {
        Swal.fire("Error", result.error || "Could not add link", "error");
      }
    } catch (err) {
      console.error("Add video reference link error:", err);
      Swal.fire("Error", "See console for details", "error");
    }
  }

  async function loadVideoReferences(individualAssignmentId, listElId) {
    const listEl = document.getElementById(listElId);
    if (!listEl) return;

    try {
      const res = await fetch(`/video_reference/list/${individualAssignmentId}`);
      if (!res.ok) return;
      const data = await res.json();
      const files = data.files || [];

      if (files.length === 0) {
        listEl.innerHTML = "";
        return;
      }

      listEl.innerHTML = files.map(f => `
        <div class="flex items-center justify-between gap-2 py-0.5">
          ${f.source_type === "link"
            ? `<a href="${f.external_url}" target="_blank" rel="noopener noreferrer" class="truncate text-blue-300 hover:underline">🔗 ${f.external_url}</a>`
            : `<span class="truncate" title="${f.file_name}">🎥 ${f.file_name}</span>`}
          <button type="button"
                  class="videoref-delete text-red-400 hover:text-red-300 shrink-0"
                  data-videoref-id="${f.id}"
                  data-assignment-id="${individualAssignmentId}"
                  title="Delete this video reference">✕</button>
        </div>
      `).join("");
    } catch (err) {
      console.warn("Could not load video references:", err);
    }
  }

  document.addEventListener("click", async (e) => {
    const btn = e.target.closest && e.target.closest(".videoref-delete");
    if (!btn) return;

    const videoRefId = btn.dataset.videorefId;
    const assignmentId = btn.dataset.assignmentId;

    const result = await Swal.fire({
      title: "Delete this video reference?",
      text: "This can't be undone.",
      icon: "warning",
      showCancelButton: true,
      confirmButtonColor: "#d33",
      confirmButtonText: "Yes, delete it"
    });
    if (!result.isConfirmed) return;

    try {
      const res = await fetch(`/video_reference/${videoRefId}`, { method: "DELETE" });
      const data = await res.json();
      if (res.ok) {
        loadVideoReferences(assignmentId, `videoref-list-${assignmentId}`);
      } else {
        Swal.fire("Error", data.error || "Delete failed", "error");
      }
    } catch (err) {
      console.error("Delete video reference error:", err);
      Swal.fire("Error", "See console for details", "error");
    }
  });

  document.addEventListener("click", async (e) => {
    const btn = e.target.closest && e.target.closest(".videoref-link-submit");
    if (!btn) return;

    const assignmentId = btn.dataset.assignmentId;
    const input = document.getElementById(btn.dataset.linkInput);
    const url = input ? input.value.trim() : "";
    if (!url) return;

    await addVideoReferenceLink(assignmentId, url);
    if (input) input.value = "";
  });

  // File picker
  document.addEventListener("change", async (e) => {
    const input = e.target;
    if (!input.matches(".videoref-upload")) return;
    const assignmentId = input.dataset.assignmentId;
    const zone = document.getElementById(`videoref-dropzone-${assignmentId}`);
    if (input.files && input.files.length > 0) {
      await uploadVideoReference(assignmentId, input.files[0], zone);
      input.value = "";
    }
  });

  // Drag-and-drop
  document.addEventListener("dragover", (e) => {
    const zone = e.target.closest && e.target.closest(".videoref-dropzone");
    if (!zone) return;
    e.preventDefault();
    zone.classList.add("border-blue-400", "bg-gray-700");
  });

  document.addEventListener("dragleave", (e) => {
    const zone = e.target.closest && e.target.closest(".videoref-dropzone");
    if (!zone) return;
    zone.classList.remove("border-blue-400", "bg-gray-700");
  });

  document.addEventListener("drop", async (e) => {
    const zone = e.target.closest && e.target.closest(".videoref-dropzone");
    if (!zone) return;
    e.preventDefault();
    zone.classList.remove("border-blue-400", "bg-gray-700");

    const assignmentId = zone.dataset.assignmentId;
    const dropped = e.dataTransfer && e.dataTransfer.files;
    if (dropped && dropped.length > 0) {
      await uploadVideoReference(assignmentId, dropped[0], zone);
    }
  });

  async function getCurrentSemesterId() {
    const resp = await fetch("/semesters/current");
    if (!resp.ok) {
      throw new Error("No active semester found");
    }
    const semester = await resp.json();
    return semester.id;
  }

  async function updateAssignmentStatus(individual_assignment_id, step_id, newStatus) {
    try {
      const res = await fetch("/dashboard/api/update-status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          individual_assignment_id,
          step_id,
          current_status: newStatus,
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || "Failed to update status");
      }

      console.log(`✅ Updated status for assignment ${individual_assignment_id}`);
    } catch (err) {
      console.error("❌ Failed to update assignment status:", err);
    }
  }

  // ------ THIS BELOW IS WHERE THE TEST SEMESTER IS ! ------------------------------------------------------------------------------------------------
  async function fetchUserAssignmentsForSemester() {
    try {
      const currentSemesterRes = await fetch("/semesters/current");
      const semesterData = await currentSemesterRes.json();

      const semesterId = window.testSemesterId || semesterData.id; // <--------------------------------right here change back to the commented
      //const semesterId = semesterData.id;

      const userParam = window.testUserId ? `&user_id=${window.testUserId}` : "";
      const res = await fetch(`/dashboard/api/user_assignments?semester_id=${semesterId}${userParam}`);

      const data = await res.json();

      if (res.ok) {
        const assignments = data.todo || data;   // ✅ fallback if no .todo
        renderTodoAssignments(assignments);
      } else {
        console.error("❌ Error loading dashboard assignments:", data.error);
      }

    } catch (err) {
      console.error("❌ Error fetching assignments:", err);
    }
  }

  // Shows the assignment's actual current status, not a guess. The server
  // already computes current_step (the step that's neither its workflow's
  // first nor last node) — look up that step's real status text and its
  // own configured node color and show exactly that, so the badge can
  // never disagree with the step's own dropdown. Falls back to a plain
  // not-started/approved read when no step is "current" (nothing touched
  // yet, or everything's already at a terminal node).
  function computeAssignmentBadge(steps) {
    const currentStepName = steps[0]?.current_step;

    if (currentStepName) {
      const activeStep = steps.find(s => s.step_name === currentStepName);
      if (activeStep) {
        const opt = (activeStep.dropdown_options || []).find(o => o.name === activeStep.assignment_status);
        return { label: activeStep.assignment_status || currentStepName, color: opt?.color || "#ca8a04" };
      }
    }

    // A step only counts as "started" once its status has actually moved
    // past its own workflow's not-started node (dropdown_options[0], same
    // first-node convention assignment_service.py's current_step_name
    // logic already uses server-side) -- a status equal to that
    // not-started node (e.g. "Standby") is still a truthy JS string, but
    // it doesn't mean the student has actually begun.
    const anyStatusSet = steps.some(s => {
      if (!s.assignment_status) return false;
      const notStartedNode = s.dropdown_options?.[0]?.name;
      return s.assignment_status !== notStartedNode;
    });
    return anyStatusSet
      ? { label: "Approved", color: "#15803d" }
      : { label: "Not started", color: "#4b5563" };
  }

  async function renderTodoAssignments(assignments) {
    const container = document.getElementById("todo-table-body");
    if (!container) return;

    container.innerHTML = "";

    if (!assignments || assignments.length === 0) {
      container.innerHTML = `<p class="text-center text-gray-400 py-4">No assignments to show</p>`;
      return;
    }

    console.log("First assignment object:", assignments[0]);

    // Group by class_name + class_id
    const groupedByClass = assignments.reduce((acc, a) => {
      const key = `${a.class_name}||${a.class_id}`;
      if (!acc[key]) acc[key] = [];
      acc[key].push(a);
      return acc;
    }, {});

    for (const [classKey, classAssignments] of Object.entries(groupedByClass)) {
      const [class_name, class_id] = classKey.split("||");

      // Fetch grade summary for this class
      let gradeSummary = null;
      try {
        const gradeRes = await fetch(`/dashboard/api/grade_summary?class_id=${class_id}`);
        if (gradeRes.ok) gradeSummary = await gradeRes.json();
      } catch (err) {
        console.warn("Could not load grade summary for class", class_id);
      }

      const classSection = document.createElement("div");
      classSection.classList.add("class-section", "bg-gray-800", "rounded-lg", "overflow-hidden");

      const classBodyId = `class-body-${class_id}`;
      classSection.innerHTML = `
        <div class="class-header flex items-center justify-between bg-gray-600 px-4 py-3 cursor-pointer"
             onclick="toggleClassSection(this)">
          <div class="flex items-center gap-2">
            <span class="chevron text-white">▾</span>
            <span class="text-white font-bold text-lg">${class_name}</span>
          </div>
          ${gradeSummary ? `
            <div class="flex gap-6 text-sm">
              <span class="text-green-400 font-semibold">
                Current Grade:
                <span class="text-white">${gradeSummary.current_letter}</span>
                <span class="text-gray-300">(${gradeSummary.current_points}/${gradeSummary.current_max})</span>
              </span>
              <span class="text-yellow-400 font-semibold">
                Grade if no more submissions:
                <span class="text-white">${gradeSummary.projected_letter}</span>
                <span class="text-gray-300">(${gradeSummary.projected_points}/${gradeSummary.projected_max})</span>
              </span>
            </div>
          ` : ""}
        </div>
        <div id="${classBodyId}" class="grid gap-3 p-4" style="grid-template-columns:repeat(auto-fit,minmax(260px,1fr))"></div>
      `;
      container.appendChild(classSection);

      const classBody = classSection.querySelector(`#${classBodyId}`);

      // Group assignments within this class by assignment_name
      const groupedByAssignment = classAssignments.reduce((acc, a) => {
        const key = `${a.assignment_name}||${a.completion_date}||${a.individual_assignment_id}`;
        if (!acc[key]) acc[key] = [];
        acc[key].push(a);
        return acc;
      }, {});

      for (const [assignKey, steps] of Object.entries(groupedByAssignment)) {
        const [assignment_name, completion_date, individual_assignment_id] = assignKey.split("||");

        // Find this assignment's grade breakdown from summary
        const assignmentGrade = gradeSummary?.assignments?.find(
          a => a.assignment_name === assignment_name
        );

        // Build OPEN button URI — scoped to this specific assignment so
        // Assignments.py opens straight into it instead of showing a picker.
        const assignmentId = steps[0]?.assignment_id || "";
        const loginName = window.currentLoginName || "";
        const openUri = assignmentId && loginName
          ? `shottracker://open?class_id=${class_id}&login_name=${encodeURIComponent(loginName)}&assignment_id=${assignmentId}`
          : null;

        const openButtonHTML = openUri
          ? `<a href="${openUri}"
              class="flex-1 text-center text-xs font-bold bg-green-600 hover:bg-green-700 text-white px-3 py-2 rounded"
              title="Open in Maya">
              🎬 OPEN
            </a>`
          : `<span class="flex-1 text-center text-xs text-gray-500 py-2">—</span>`;

        const latestVersion = steps[0]?.latest_version;
        const versionHTML = latestVersion ? `<span title="Latest saved version">💾 v${latestVersion}</span>` : "";

        const currentFileStep = steps[0]?.current_file_step;
        const currentStepHTML = currentFileStep ? `<span title="Current step (from saved files)">📍 ${currentFileStep}</span>` : "";

        const badge = computeAssignmentBadge(steps);

        const card = document.createElement("div");
        card.classList.add("assignment-card", "bg-gray-900", "rounded-lg", "p-4");
        card.dataset.assignmentId = individual_assignment_id;

        const reviewGroupId = `review-group-${individual_assignment_id}`;
        const stepsId = `steps-${individual_assignment_id}`;
        const historyId = `history-row-${individual_assignment_id}`;

        card.innerHTML = `
          <div class="flex items-start justify-between mb-2">
            <span class="text-white font-bold">${assignment_name}</span>
            <div class="flex flex-col items-end gap-1">
              <span class="text-xs px-2 py-1 rounded" style="background-color:${badge.color};color:#000">${badge.label}</span>
              <span class="text-xs text-green-400">${assignmentGrade ? `${assignmentGrade.earned}/${assignmentGrade.max_points}` : "—"}</span>
            </div>
          </div>
          <div class="flex items-center gap-3 text-xs text-gray-400 mb-3">
            <span>Due ${completion_date || "—"}</span>
            ${currentStepHTML}
            ${versionHTML}
          </div>
          <div class="flex gap-2 mb-2">
            ${openButtonHTML}
            <button class="text-xs bg-gray-600 hover:bg-gray-500 text-white px-2 py-1 rounded"
                    onclick="toggleSteps(this, '${stepsId}')">
              Steps ▾
            </button>
            <button class="text-xs bg-gray-600 hover:bg-gray-500 text-white px-2 py-1 rounded"
                    onclick="toggleHistory(this, ${individual_assignment_id})">
              History ▾
            </button>
          </div>
          <div id="${reviewGroupId}" class="flex gap-2 mb-2"></div>
          <div id="${stepsId}" class="hidden border-t border-gray-700 mt-2 pt-2 space-y-2"></div>
          <div id="${historyId}" class="hidden border-t border-gray-700 mt-2 pt-2">
            <div id="history-content-${individual_assignment_id}" class="text-sm text-gray-300">Loading...</div>
          </div>
        `;
        classBody.appendChild(card);

        // Steps panel — one row per step, preserving the status dropdown
        const stepsPanel = card.querySelector(`#${stepsId}`);
        steps.forEach(step => {
          const { step_id, step_name, assignment_status, dropdown_options, grades } = step;

          const dropdownId = `dropdown-${individual_assignment_id}-${step_id}`;
          const dropdownHTML = (dropdown_options && dropdown_options.length > 0) ? `
            <select id="${dropdownId}"
                    class="status-dropdown bg-gray-200 text-black px-2 py-1 rounded text-sm cursor-pointer"
                    data-assignment-id="${individual_assignment_id}"
                    data-step-id="${step_id}"
                    onchange="handleStatusChange(this)">
              ${dropdown_options.map(option => `
                <option value="${option.name}"
                        ${assignment_status === option.name ? "selected" : ""}
                        style="background-color:${option.color}; color:#000;"
                        data-color="${option.color}">
                  ${option.name}
                </option>
              `).join("")}
            </select>` : "—";

          const stepRow = document.createElement("div");
          stepRow.classList.add("flex", "items-center", "justify-between", "gap-2", "text-sm");
          stepRow.innerHTML = `
            <span class="text-gray-300">${step_name}</span>
            ${dropdownHTML}
            <span class="text-gray-400 text-xs">${(grades && grades.length > 0) ? grades.join(", ") : "—"}</span>
          `;
          stepsPanel.appendChild(stepRow);

          setTimeout(() => {
            const dropdown = document.getElementById(dropdownId);
            if (dropdown) updateDropdownColor(dropdown);
          }, 0);

          // 🖊️ Planning drawings upload — only shown for assignments whose
          // workflow actually includes a Planning step.
          if (step_name === "Planning") {
            const dropzoneId = `planning-dropzone-${individual_assignment_id}`;
            const inputId = `planning-input-${individual_assignment_id}`;
            const listId = `planning-list-${individual_assignment_id}`;

            const planningRow = document.createElement("div");
            planningRow.classList.add("mt-1", "mb-1");
            planningRow.innerHTML = `
              <label id="${dropzoneId}" for="${inputId}"
                     class="planning-dropzone cursor-pointer flex items-center justify-center gap-1
                            text-xs text-gray-300 border border-dashed border-gray-500 rounded
                            px-2 py-2 hover:bg-gray-700 hover:border-blue-400 transition"
                     data-assignment-id="${individual_assignment_id}">
                🖼️ Drop planning drawings here or click to upload
              </label>
              <input id="${inputId}" type="file" accept="image/png,image/jpeg" multiple
                     class="hidden planning-drawings-upload"
                     data-assignment-id="${individual_assignment_id}" />
              <div id="${listId}" class="text-gray-400 text-xs mt-1"></div>
            `;
            stepsPanel.appendChild(planningRow);

            loadPlanningDrawings(individual_assignment_id, listId);

            // 🎥 Video reference — upload a clip (converted server-side,
            // synchronous so this can take a little while) or paste a link.
            const vrDropzoneId = `videoref-dropzone-${individual_assignment_id}`;
            const vrInputId = `videoref-input-${individual_assignment_id}`;
            const vrLinkInputId = `videoref-link-input-${individual_assignment_id}`;
            const vrListId = `videoref-list-${individual_assignment_id}`;

            const videoRefRow = document.createElement("div");
            videoRefRow.classList.add("mt-2", "mb-1");
            videoRefRow.innerHTML = `
              <label id="${vrDropzoneId}" for="${vrInputId}"
                     class="videoref-dropzone cursor-pointer flex items-center justify-center gap-1
                            text-xs text-gray-300 border border-dashed border-gray-500 rounded
                            px-2 py-2 hover:bg-gray-700 hover:border-blue-400 transition"
                     data-assignment-id="${individual_assignment_id}">
                🎥 Drop a reference video here or click to upload
              </label>
              <input id="${vrInputId}" type="file" accept="video/*"
                     class="hidden videoref-upload"
                     data-assignment-id="${individual_assignment_id}" />
              <div class="flex gap-1 mt-1">
                <input id="${vrLinkInputId}" type="text" placeholder="...or paste a video link"
                       class="videoref-link-text flex-1 bg-gray-700 text-white text-xs px-2 py-1 rounded" />
                <button type="button"
                        class="videoref-link-submit text-xs bg-gray-600 hover:bg-gray-500 text-white px-2 rounded"
                        data-assignment-id="${individual_assignment_id}"
                        data-link-input="${vrLinkInputId}">Add</button>
              </div>
              <div id="${vrListId}" class="text-gray-400 text-xs mt-1"></div>
            `;
            stepsPanel.appendChild(videoRefRow);

            loadVideoReferences(individual_assignment_id, vrListId);
          }
        });

        // Reviews — aggregated across all steps for this assignment (the
        // card no longer has one row per step, so no ?step= filter here).
        const reviewGroup = card.querySelector(`#${reviewGroupId}`);
        fetch(`/dashboard/api/reviews/${encodeURIComponent(assignment_name)}`)
          .then(res => res.json())
          .then(data => {
            if (!(data.exists && Array.isArray(data.reviews) && data.reviews.length > 0)) return;

            const uniqueReviews = Array.from(
              new Map(data.reviews.map(r => [r.path, r])).values()
            );
            uniqueReviews.sort((a, b) => new Date(b.date) - new Date(a.date));

            const latest = uniqueReviews[0];
            const older = uniqueReviews.length > 1 ? uniqueReviews[1] : null;

            let html = `
              <a href="${latest.path}" target="_blank"
                class="flex-1 text-center bg-green-700 hover:bg-green-600 text-white px-2 py-1 text-xs rounded">
                Latest Review
              </a>
            `;
            if (older && older.path !== latest.path) {
              html += `
                <a href="${older.path}" target="_blank"
                  class="flex-1 text-center bg-gray-600 hover:bg-gray-500 text-white px-2 py-1 text-xs rounded">
                  Older Review
                </a>
              `;
            }
            reviewGroup.innerHTML = html;
          })
          .catch(() => {});
      }
    }
  }

  window.toggleClassSection = function (headerEl) {
    const body = headerEl.nextElementSibling;
    const chevron = headerEl.querySelector(".chevron");
    if (!body) return;
    const isHidden = body.classList.toggle("hidden");
    if (chevron) chevron.textContent = isHidden ? "▸" : "▾";
  };

  window.toggleSteps = function (btn, stepsId) {
    const panel = document.getElementById(stepsId);
    if (!panel) return;
    const isHidden = panel.classList.toggle("hidden");
    btn.textContent = isHidden ? "Steps ▾" : "Steps ▴";
  };

  // History toggle
  async function toggleHistory(btn, individualAssignmentId) {
    const row = document.getElementById(`history-row-${individualAssignmentId}`);
    const content = document.getElementById(`history-content-${individualAssignmentId}`);

    if (!row) return;

    const isHidden = row.classList.contains("hidden");
    row.classList.toggle("hidden");
    btn.textContent = isHidden ? "History ▴" : "History ▾";

    if (isHidden) {
      try {
        const res = await fetch(`/dashboard/api/grade_history/${individualAssignmentId}`);
        const data = await res.json();

        if (!data.history || data.history.length === 0) {
          content.innerHTML = "<span class='text-gray-500 italic'>No grade history yet.</span>";
          return;
        }

        content.innerHTML = `
          <table class="text-xs w-full">
            <thead>
              <tr class="text-gray-400">
                <th class="text-left pr-4">Step</th>
                <th class="text-left pr-4">From</th>
                <th class="text-left pr-4">To</th>
                <th class="text-left pr-4">Date</th>
              </tr>
            </thead>
            <tbody>
              ${data.history.map(h => `
                <tr class="border-t border-gray-700">
                  <td class="pr-4 py-1">${h.step_name}</td>
                  <td class="pr-4 py-1 text-red-400">${h.old_grade}</td>
                  <td class="pr-4 py-1 text-green-400">${h.new_grade}</td>
                  <td class="pr-4 py-1 text-gray-400">${h.changed_at}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        `;
      } catch (err) {
        content.innerHTML = "<span class='text-red-400'>Error loading history.</span>";
      }
    }
  }


  async function updateAssignmentStatus(individual_assignment_id, step_id, newStatus) {
    if (!individual_assignment_id || !step_id || !newStatus) {
      console.warn("⚠️ Missing assignment_id, step_id, or status");
      return;
    }

    try {
      const res = await fetch("/dashboard/api/update-status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_type: "assignment",                 // ✅ match backend
          task_id: individual_assignment_id,       // ✅ match backend
          step_id,
          new_status: newStatus,                   // ✅ match backend
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err?.error || "Failed to update status");
      }

      console.log(`✅ Status updated: ${individual_assignment_id} — ${step_id} => ${newStatus}`);

      Swal.fire({
        icon: "success",
        title: "Status updated!",
        text: `Step ${step_id} saved as: ${newStatus}`,
        timer: 1500,
        showConfirmButton: false,
      });

    } catch (err) {
      console.error("❌ Failed to update status:", err);
      Swal.fire({
        icon: "error",
        title: "Update failed",
        text: err.message || "Something went wrong",
      });
    }
  }




  function handleStatusChange(dropdown) {
    updateDropdownColor(dropdown);
    const individual_assignment_id = dropdown.dataset.assignmentId;
    const step_id = dropdown.dataset.stepId;
    const newStatus = dropdown.value;
    updateAssignmentStatus(individual_assignment_id, step_id, newStatus);
  }



  document.addEventListener('DOMContentLoaded', () => {
    const select = document.getElementById('debugSemesterSelect');
    if (!select) return;

    // Restore previously selected override (if any)
    const saved = localStorage.getItem("debugSemesterId");
    if (saved) {
      select.value = saved;
      window.testSemesterId = parseInt(saved);
    }

    select.addEventListener('change', () => {
      const val = select.value;
      if (val) {
        localStorage.setItem("debugSemesterId", val);
        window.testSemesterId = parseInt(val);
      } else {
        localStorage.removeItem("debugSemesterId");
        delete window.testSemesterId;
      }
      location.reload();
    });
  });



  // ✅ Real-time color update
  function updateDropdownColor(selectElement) {
    const selectedOption = selectElement.options[selectElement.selectedIndex];
    const color = selectedOption?.getAttribute("data-color");
    if (color) {
      // ✅ apply background only to the closed dropdown (selected state)
      selectElement.style.backgroundColor = color;
      selectElement.style.color = "#000";  // adjust text so it’s readable
      selectElement.style.border = `2px solid ${color}`;
    } else {
      // reset if no color
      selectElement.style.backgroundColor = "";
      selectElement.style.color = "";
      selectElement.style.border = "";
    }
  }




  function updateTodoAssignmentsTable(assignments) {
    const tbody = document.querySelector("#user-assignments-table tbody");
    if (!tbody) return;

    tbody.innerHTML = "";

    assignments.forEach(assignment => {
      const row = document.createElement("tr");
      row.classList.add("border-t", "text-black");

      const nameCell = `<td class="p-3">${assignment.assignment_name}</td>`;
      const startDate = `<td class="p-3">${assignment.start_date}</td>`;
      const completionDate = `<td class="p-3">${assignment.completion_date}</td>`;
      const status = `<td class="p-3 text-gray-300">${assignment.current_status}</td>`;
      const grade = `<td class="p-3 text-gray-400">${assignment.grade}</td>`;
      const upload = `<td class="p-3"><button class="btn btn-sm">Upload</button></td>`;

      row.innerHTML = nameCell + startDate + completionDate + status + grade + upload;
      tbody.appendChild(row);
    });
  }

  async function fetchUserAssignments() {
    const tableBody = document.querySelector("#user-assignments-table tbody");
    tableBody.innerHTML = "";

    try {
      const response = await fetch("/dashboard/api/user_assignments");
      const assignments = await response.json();

      assignments.forEach(assignment => {
        const row = document.createElement("tr");

        // // Build the dropdown
        // const statusOptions = ["Not Started", "In Progress", "Completed"];
        // const statusDropdown = `
        //         <select disabled>
        //             ${statusOptions.map(status => `
        //                 <option value="${status}" ${status === assignment.current_status ? "selected" : ""}>${status}</option>
        //             `).join("")}
        //         </select>
        //     `;

        const uploadButton = `
                <input type="file" id="file-upload-${assignment.id}" hidden>
                <button onclick="document.getElementById('file-upload-${assignment.id}').click()">Upload</button>
            `;

        row.innerHTML = `
                <td>${assignment.assignment_name}</td>
                <td>${assignment.start_date}</td>
                <td>${assignment.completion_date}</td>
                <td>${statusDropdown}</td>
                <td><input type="text" value="${assignment.grade}" readonly></td>
                <td>${uploadButton}</td>
            `;

        tableBody.appendChild(row);
      });
    } catch (err) {
      console.error("❌ Error loading assignments:", err);
    }
  }

  function renderTodoTable(assignments) {
    const tbody = document.querySelector("#todo-table tbody");
    tbody.innerHTML = "";
    assignments.forEach(item => {
      const row = document.createElement("tr");
      row.innerHTML = `
            <td>${item.assignment_name}</td>
            <td>${item.class_name}</td>
            <td>${item.step_name}</td>
            <td>${item.current_status}</td>
        `;
      tbody.appendChild(row);
    });
  }

  function renderGradedTable(assignments) {
    const tbody = document.querySelector("#graded-table tbody");
    tbody.innerHTML = "";
    assignments.forEach(item => {
      const row = document.createElement("tr");
      row.innerHTML = `
            <td>${item.assignment_name}</td>
            <td>${item.class_name}</td>
            <td>${item.step_name}</td>
            <td>${item.current_status}</td>
        `;
      tbody.appendChild(row);
    });
  }


  async function fetchAndRenderUserClasses() {
    try {
      const response = await fetch("/dashboard/api/user_classes");
      const data = await response.json();

      if (!response.ok || !Array.isArray(data)) {
        throw new Error("Invalid class data");
      }

      renderCollapsibleClasses(data);
    } catch (err) {
      console.error("❌ Failed to load classes:", err);
    }
  }

  async function renderCollapsibleClasses() {
    const container = document.getElementById("class-collapsible-list");
    if (!container) {
      console.warn("⚠️ Missing #class-collapsible-list");
      return;
    }

    container.innerHTML = "<p class='text-gray-400'>Loading...</p>";

    try {
      const res = await fetch("/review/api/graded_assignments_with_files");
      const data = await res.json();

      if (!res.ok || !Array.isArray(data)) throw new Error("Invalid graded assignments");

      if (data.length === 0) {
        container.innerHTML = "<p class='text-gray-400'>No graded assignments yet.</p>";
        return;
      }

      // Group by class
      const grouped = {};
      data.forEach(item => {
        if (!grouped[item.class_name]) grouped[item.class_name] = [];
        grouped[item.class_name].push(item);
      });

      container.innerHTML = "";

      for (const [className, assignments] of Object.entries(grouped)) {
        const section = document.createElement("div");
        section.classList.add("class-section", "mb-2", "bg-gray-800", "rounded", "shadow");

        const header = document.createElement("div");
        header.classList.add("cursor-pointer", "p-3", "text-white", "font-semibold", "bg-gray-700", "rounded-t");
        header.innerText = className;
        header.addEventListener("click", () => content.classList.toggle("hidden"));

        const content = document.createElement("div");
        content.classList.add("p-3", "bg-gray-900", "text-white", "hidden");

        assignments.forEach(assign => {
          const item = document.createElement("div");
          item.classList.add("flex", "justify-between", "items-center", "py-1", "border-b", "border-gray-700");

          const name = document.createElement("span");
          name.innerText = `${assign.assignment_name} — ${assign.grade || "Ungraded"}`;

          const viewBtn = document.createElement("a");
          viewBtn.href = `/review/get_video?path=${encodeURIComponent(assign.file_path)}`;
          viewBtn.target = "_blank";
          viewBtn.className = "bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium px-3 py-1 rounded shadow";
          viewBtn.innerText = "View";

          item.appendChild(name);
          item.appendChild(viewBtn);
          content.appendChild(item);
        });

        section.appendChild(header);
        section.appendChild(content);
        container.appendChild(section);
      }
    } catch (err) {
      console.error("❌ Failed to load graded classes:", err);
      container.innerHTML = "<p class='text-red-400'>Error loading graded assignments.</p>";
    }
  }


  async function loadStudentDropdown() {
    const select = document.getElementById("userSelect");
    if (!select) return;

    console.log("📢 Fetching student list...");

    try {
      const res = await fetch("/dashboard/admin/api/students");
      const users = await res.json();

      console.log("✅ Students loaded:", users);

      if (!Array.isArray(users)) {
        console.warn("⚠️ Unexpected response (not an array):", users);
        if (users.error) {
          const option = document.createElement("option");
          option.textContent = `⚠️ ${users.error}`;
          option.disabled = true;
          select.appendChild(option);
        }
        return;
      }

      users.forEach(user => {
        const option = document.createElement("option");
        option.value = user.id;
        option.textContent = user.name;
        select.appendChild(option);
      });

      select.addEventListener("change", () => {
        const selectedId = select.value;
        if (!selectedId) return;

        console.log("👥 Selected user ID:", selectedId);
        window.testUserId = selectedId;
        fetchUserAssignmentsForSemester();
      });

    } catch (err) {
      console.error("❌ Failed to load students:", err);
    }
  }






  document.addEventListener("DOMContentLoaded", () => {
    fetchAndRenderUserClasses();
    fetchUserAssignmentsForSemester();

    if (window.is_admin === true || window.is_admin === "true") {
      console.log("👑 Admin detected, loading dropdown...");
      loadStudentDropdown();
    } else {
      console.log("👤 Not an admin — skipping dropdown.");
    }
  });

