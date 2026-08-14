//--------------------------------------------------------------------------------------------------------
// DOM READY
//--------------------------------------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  console.log("✅ shots.js loaded");

  // Initialize Step Checkboxes
  const checkboxes = document.querySelectorAll("#step-checkboxes input[type=checkbox]");
  checkboxes.forEach(cb => {
    const stepName = cb.dataset.stepName.trim();
    if (stepName && stepName !== "❌ NO NAME") {
      const label = cb.nextElementSibling;
      if (label) label.textContent = stepName;
    }
  });

  // Bulk Select / Deselect Logic
  const allStepsButton = document.getElementById('show-all-steps');
  const artistStepsButton = document.getElementById('show-artist-steps');

  if (allStepsButton) {
    allStepsButton.addEventListener("click", (event) => {
      event.preventDefault();
      checkboxes.forEach(cb => cb.checked = true);
    });
  }

  if (artistStepsButton) {
    artistStepsButton.addEventListener("click", (event) => {
      event.preventDefault();
      checkboxes.forEach(cb => {
        const isArtistStep = !cb.dataset.stepName.includes("fb");
        cb.checked = isArtistStep;
      });
    });
  }

  // ✅ Handle Scene Dropdown Navigation
  const sceneDropdown = document.getElementById("scene-dropdown");
  if (sceneDropdown) {
    sceneDropdown.addEventListener("change", function () {
      const sceneId = this.value;
      if (sceneId) {
        window.location.href = `/films/scenes/${sceneId}/shots`;
      }
    });
  }

  // Bulk Edit Button Handler
  const bulkEditButton = document.getElementById("edit-selected-btn");
  if (bulkEditButton) {
    bulkEditButton.addEventListener("click", openBulkEditModal);
  }

  // Bulk Edit Modal Submission Handler
  const bulkEditForm = document.getElementById("bulk-edit-form");
  if (bulkEditForm) {
    bulkEditForm.addEventListener("submit", handleBulkEditSubmit);
  }


  const editShotForm = document.getElementById("edit-shot-form");

  if (editShotForm) {
    editShotForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      const formData = new FormData(this);

      try {
        const response = await fetch(this.action, {
          method: "POST",
          headers: {
            "X-Requested-With": "XMLHttpRequest"
          },
          body: formData
        });

        const data = await response.json();

        if (data.success) {
          closeEditModal();  // Close the modal
          location.reload();  // Refresh to reflect the changes
        } else {
          alert("Error: " + data.message);
        }
      } catch (error) {
        alert("An error occurred. Please try again.");
        console.error("Error:", error);
      }
    });
  }

  // ✅ Filter Status by Step
  const stepDropdown = document.getElementById("step-filter");
  const statusDropdown = document.getElementById("status-filter");

  if (stepDropdown && statusDropdown) {
    const allStatusOptions = Array.from(statusDropdown.options);

    function filterStatusesByStep(stepId) {
      const selectedStatus = statusDropdown.value;
      statusDropdown.innerHTML = "";

      const filteredOptions = allStatusOptions.filter(opt => {
        const stepAttr = opt.getAttribute("data-step");
        return !stepId || stepAttr === stepId || opt.value === "";
      });

      filteredOptions.forEach(opt => statusDropdown.appendChild(opt));

      // Restore selection if possible
      if (selectedStatus && [...statusDropdown.options].some(o => o.value === selectedStatus)) {
        statusDropdown.value = selectedStatus;
      }
    }

    // Initial filter
    filterStatusesByStep(stepDropdown.value);

    // On change
    stepDropdown.addEventListener("change", function () {
      filterStatusesByStep(this.value);
    });
  }

  // Crossflow Status Update Logic
  document.querySelectorAll(".status-dropdown").forEach(dropdown => {
    dropdown.addEventListener("change", async (event) => {
      const select = event.target;
      const shotId = select.dataset.shotId;
      const stepId = select.dataset.stepId;
      const newStatus = select.value;

      const selectedOption = select.options[select.selectedIndex];
      const newNodeId = selectedOption.getAttribute("data-node-id");  // ✅ real node_id

      try {
        await updateStepStatus(shotId, stepId, newStatus);
        await handleCrossflowUpdates(shotId, stepId, newNodeId);  // ✅ use node_id here
        console.log(`✅ Status updated for shot ${shotId}, step ${stepId} to ${newStatus}`);
      } catch (error) {
        console.error("❌ Error updating crossflow status:", error);
        alert("Failed to update crossflow status. Please try again.");
      }
    });
  });
  

  // Initialize filter panel toggle
  const filterPanel = document.getElementById("scene-filter-form");
  const toggleButton = document.getElementById("toggle-filter-panel");

  if (filterPanel && toggleButton) {
    // ✅ Check if the panel is visible on load
    const isVisible = !filterPanel.classList.contains("hidden");
    toggleButton.textContent = isVisible ? "Hide Filters" : "Show Filters";

    // ✅ Handle button click
    toggleButton.addEventListener("click", () => {
      filterPanel.classList.toggle("hidden");
      const isVisibleNow = !filterPanel.classList.contains("hidden");
      toggleButton.textContent = isVisibleNow ? "Hide Filters" : "Show Filters";
    });

    // ✅ Start with the panel hidden
    if (isVisible) {
      filterPanel.classList.add("hidden");
      toggleButton.textContent = "Show Filters";
    }
  }

});

//--------------------------------------------------------------------------------------------------------
// BULK SELECT + DELETE
//--------------------------------------------------------------------------------------------------------

function toggleAll(source) {
  document.querySelectorAll('input[name="shot_ids"]').forEach(cb => cb.checked = source.checked);
}

document.getElementById("confirm-delete-selected")?.addEventListener("click", () => {
  const anyChecked = document.querySelectorAll('input[name="shot_ids"]:checked').length > 0;

  if (!anyChecked) {
    Swal.fire({
      icon: 'info',
      title: 'No shots selected',
      text: 'Please check at least one shot to delete.',
    });
    return;
  }

  Swal.fire({
    title: 'Are you sure?',
    text: "This will permanently delete the selected shots.",
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#d33',
    cancelButtonColor: '#888',
    confirmButtonText: 'Yes, delete them!'
  }).then((result) => {
    if (result.isConfirmed) {
      document.getElementById("delete-multiple-form").submit();
    }
  });
});

function confirmDeleteShot(shotId) {
  Swal.fire({
    title: 'Are you sure?',
    text: "This will permanently delete the shot.",
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#d33',
    cancelButtonColor: '#3085d6',
    confirmButtonText: 'Yes, delete it!'
  }).then((result) => {
    if (result.isConfirmed) {
      document.getElementById(`delete-shot-form-${shotId}`).submit();
    }
  });
}

function approveShotStep(button, endpoint, stepLabel, nextStepLabel) {
  const shotId = button.dataset.shotId;
  const loginName = button.dataset.loginName;

  const text = nextStepLabel
    ? `Locks ${stepLabel} for this shot and makes ${nextStepLabel} reachable.`
    : `Locks ${stepLabel} for this shot.`;

  Swal.fire({
    title: `Approve this shot's ${stepLabel}?`,
    text: text,
    icon: 'question',
    showCancelButton: true,
    confirmButtonColor: '#15803d',
    cancelButtonColor: '#3085d6',
    confirmButtonText: 'Yes, approve it',
    cancelButtonText: 'Cancel'
  }).then((result) => {
    if (!result.isConfirmed) return;

    fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ shot_id: shotId, login_name: loginName })
    })
      .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) {
          Swal.fire('Error', data.error || `Could not approve ${stepLabel}.`, 'error');
          return;
        }
        const warning = data.timeline_warning ? `\n\n${data.timeline_warning}` : '';
        Swal.fire('Approved', `${stepLabel} approved.${warning}`, data.timeline_warning ? 'warning' : 'success')
          .then(() => location.reload());
      })
      .catch(() => {
        Swal.fire('Error', 'Could not reach Shot Tracker.', 'error');
      });
  });
}

function approveShotLayout(button) {
  approveShotStep(button, '/classes/api/launcher/capstone/shot-layout/approve', 'Layout', 'Animation');
}

function approveShotAnimation(button) {
  approveShotStep(button, '/classes/api/launcher/capstone/shot-animation/approve', 'Animation', 'Lighting');
}

function approveShotLighting(button) {
  // No next-step gate to mention -- Comp is out of scope for this phase.
  approveShotStep(button, '/classes/api/launcher/capstone/shot-lighting/approve', 'Lighting', null);
}

// Bulk Edit Logic

function openBulkEditModal() {
  const selectedShots = Array.from(document.querySelectorAll('input[name="shot_ids"]:checked'));
  if (selectedShots.length === 0) {
    Swal.fire("No shots selected", "Select at least one shot to edit.", "info");
    return;
  }

  // Collect shot IDs
  const shotIds = selectedShots.map(cb => cb.value.trim()).join(",");
  document.getElementById("bulk-shot-ids").value = shotIds;

  // Show the bulk edit modal
  const modal = document.getElementById("bulkEditModal");
  if (modal) {
    modal.classList.remove("hidden");
  }
}

function closeBulkEditModal() {
  const modal = document.getElementById("bulkEditModal");
  if (modal) {
    modal.classList.add("hidden");
  }
}


// Make the modal draggable
function makeModalDraggable(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;

  let isDragging = false;
  let startX, startY, offsetX, offsetY;

  modal.addEventListener("mousedown", (e) => {
    isDragging = true;
    startX = e.clientX;
    startY = e.clientY;
    const rect = modal.getBoundingClientRect();
    offsetX = startX - rect.left;
    offsetY = startY - rect.top;
    modal.style.cursor = "move";
  });

  window.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    const x = e.clientX - offsetX;
    const y = e.clientY - offsetY;
    modal.style.left = `${x}px`;
    modal.style.top = `${y}px`;
    modal.style.transform = "none"; // Remove centering when dragging
  });

  window.addEventListener("mouseup", () => {
    isDragging = false;
    modal.style.cursor = "auto";
  });
}

// Initialize the draggable behavior
document.addEventListener("DOMContentLoaded", () => {
  makeModalDraggable("bulkEditModal");
});


// Bulk Edit Form Submission
async function handleBulkEditSubmit(event) {
  event.preventDefault();
  const formData = new FormData(event.target);
  const shotIds = formData.get("shot_ids").split(",").map(id => id.trim()).filter(Boolean);
  const updates = {};
  const stepUpdates = {};

  // Collect main fields (description, start date, due date)
  ["description", "start_date", "due_date"].forEach(field => {
    const value = formData.get(field);
    if (value && value.trim() !== "") {
      updates[field] = value.trim();
    }
  });

  // Collect per-step updates (status, assigned, due)
  formData.forEach((value, key) => {
    const match = key.match(/^(step_status|step_assigned|step_due)_(\d+)$/);
    if (match) {
      const [, prefix, stepId] = match;
      if (value && value.trim() !== "") {
        stepUpdates[`${prefix}_${stepId}`] = value.trim();
        console.log(`Captured step update - Key: ${prefix}_${stepId}, Value: ${value.trim()}`);
      }
    }
  });

  console.log("Collected Step Updates:", stepUpdates);

  if (Object.keys(updates).length === 0 && Object.keys(stepUpdates).length === 0) {
    Swal.fire("No Changes", "Please provide at least one field to update.", "info");
    return;
  }

  try {
    const response = await fetch("/films/films/bulk_edit_shots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ shot_ids: shotIds, updates, step_updates: stepUpdates })
    });

    const data = await response.json();

    if (data.success) {
      // ✅ After successful update, trigger crossflow for any step_status changes
      for (const [key, status] of Object.entries(stepUpdates)) {
        if (key.startsWith("step_status_")) {
          const stepId = key.split("_")[2];
          for (const shotId of shotIds) {
            const dropdown = document.querySelector(
              `select.status-dropdown[data-shot-id="${shotId}"][data-step-id="${stepId}"]`
            );
            const option = dropdown?.querySelector(`option[value="${status}"]`);
            const nodeId = option?.getAttribute("data-node-id");

            if (nodeId) {
              console.log(`🔁 Crossflow from bulk edit: Shot ${shotId}, Step ${stepId}, Node ${nodeId}`);
              await handleCrossflowUpdates(shotId, stepId, nodeId);
            } else {
              console.warn(`⚠️ No node_id found for status "${status}" on shot ${shotId}, step ${stepId}`);
            }
          }
        }
      }

      Swal.fire("Success", data.message, "success").then(() => {
        const modal = document.getElementById("bulkEditModal");
        if (modal) closeBulkEditModal();
        location.reload();
      });

    } else {
      Swal.fire("Error", data.message, "error");
    }
  } catch (error) {
    console.error("❌ Error updating shots:", error);
    Swal.fire("Error", "An unexpected error occurred. Please try again.", "error");
  }
}


// Attach the handler
const bulkEditForm = document.getElementById("bulk-edit-form");
if (bulkEditForm) {
  bulkEditForm.addEventListener("submit", handleBulkEditSubmit);
}


//--------------------------------------------------------------------------------------------------------
// STATUS UPDATES
//--------------------------------------------------------------------------------------------------------

function updateAssignedUser(shotId, stepId, userId) {
  fetch("/films/update-assigned-user", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ shot_id: shotId, step_id: stepId, user_id: userId })
  })
    .then(res => res.json())
    .then(data => console.log("✅ Assigned user updated:", data))
    .catch(err => console.error("❌ Error updating user:", err));
}

function updateStepStatus(shotId, stepId, newStatus) {
  console.log("🔄 Updating status:", {
    shotId: shotId,
    stepId: stepId,
    newStatus: newStatus
  });

  // Send the primary status update to the server
  fetch(`/films/shots/update-shot-status`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      shot_id: shotId,
      step_id: stepId,
      status: newStatus
    })
  })
    .then(response => response.json())
    .then(data => {
      console.log("✅ Status update response:", data);
      if (data.success) {
        console.log(`✅ Status updated to '${newStatus}' for Shot ${shotId}, Step ${stepId}`);
      } else {
        console.error(`❌ Failed to update status: ${data.error}`);
      }
    })
    .catch(error => console.error("❌ Error updating status:", error));
}

function updateDueDate(shotId, stepId, dueDate) {
  fetch("/films/shots/update-due-date", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ shot_id: shotId, step_id: stepId, due_date: dueDate })
  })
    .then(res => {
      if (!res.ok) throw new Error("Failed to update");
      return res.json();
    })
    .then(data => {
      console.log("📅 Due date updated:", data);
    })
    .catch(err => {
      console.error("❌ Error:", err);
      alert("Error updating due date.");
    });
}



async function bulkUpdateShotStatuses() {
  const selectedSteps = Array.from(document.querySelectorAll(".status-dropdown"))
    .filter(select => select.value !== select.dataset.initialStatus)
    .map(select => ({
      shot_id: select.dataset.shotId,
      step_id: select.dataset.stepId,
      status: select.value
    }));

  if (selectedSteps.length === 0) {
    Swal.fire("No Changes", "No statuses were changed.", "info");
    return;
  }

  try {
    const response = await fetch(`/api/films/shots/bulk-update`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ updates: selectedSteps })
    });

    const data = await response.json();
    console.log("✅ Bulk update successful:", data);
  } catch (error) {
    console.error("❌ Error during bulk status update:", error);
  }
}

// Handle crossflow status updates
async function handleCrossflowUpdates(shotId, stepId, newNodeId) {
  console.log("🔁 Crossflow update → shot:", shotId, "step:", stepId, "node:", newNodeId);

  try {
    const response = await fetch("/films/api/shot-crossflow-updates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        shot_id: shotId,
        step_id: stepId,
        node_id: newNodeId   // 👈 now using node_id, not status
      })
    });

    if (!response.ok) throw new Error("Crossflow status update failed");

    const updatedSteps = await response.json();

    updatedSteps.forEach(({ step_id, new_status, color }) => {
      const dropdown = document.querySelector(
        `select[data-shot-id="${shotId}"][data-step-id="${step_id}"]`
      );
      if (dropdown) {
        dropdown.value = new_status;
        dropdown.style.backgroundColor = color || "#ffffff";
        dropdown.style.color = "#000000";
      }
    });

  } catch (error) {
    console.error("❌ Error during crossflow update:", error);
    alert("Crossflow status update failed");
  }
}




// ✅ Add Artist Steps Only and All Steps functions
function selectAllSteps(selectAll) {
  document.querySelectorAll('#step-checkboxes input[type=checkbox]').forEach(cb => cb.checked = selectAll);
  filterSteps();
}

function selectArtistStepsOnly() {
  document.querySelectorAll('#step-checkboxes input[type=checkbox]').forEach(cb => {
    const isArtistStep = !cb.dataset.stepName.toLowerCase().includes("fb");
    cb.checked = isArtistStep;
  });
  filterSteps();
}

// ✅ Toggle visibility of a specific step
function toggleStep(stepId, isVisible) {
  document.querySelectorAll(`[data-step-column-id="${stepId}"], [data-step-progress-id="${stepId}"]`).forEach(el => {
    el.style.display = isVisible ? "" : "none";
  });
}

// ✅ Filter Steps based on checkbox selections
function filterSteps() {
  const visibleStepIds = new Set(Array.from(document.querySelectorAll('#step-checkboxes input[type=checkbox]:checked')).map(cb => parseInt(cb.value)));

  // Apply visibility to progress circles and dropdown columns
  document.querySelectorAll("[data-step-progress-id], [data-step-column-id]").forEach(el => {
    const stepId = parseInt(el.getAttribute("data-step-progress-id") || el.getAttribute("data-step-column-id"));
    el.style.display = visibleStepIds.has(stepId) ? "" : "none";
  });
}

document.addEventListener("DOMContentLoaded", () => {
  filterSteps();  // Run on page load to apply any pre-selected filters

  // Attach event listeners for individual checkbox toggles
  document.querySelectorAll('#step-checkboxes input[type=checkbox]').forEach(cb => {
    cb.addEventListener('change', () => {
      const stepId = parseInt(cb.value);
      toggleStep(stepId, cb.checked);
    });
  });
});