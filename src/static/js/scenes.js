window.sceneCharts = {};
document.addEventListener("DOMContentLoaded", function () {

  // Handle film dropdown navigation
  const dropdown = document.getElementById("film-dropdown");
  if (dropdown) {
    dropdown.addEventListener("change", function () {
      const filmId = this.value;
      if (filmId) window.location.href = `/films/${filmId}/scenes`;
    });
  }

  // Initialize scene progress charts
  const canvases = document.querySelectorAll("[id^='scene-chart-']");

  canvases.forEach(canvas => {
    const sceneId = canvas.getAttribute("data-scene-id");
    const stepId = canvas.getAttribute("data-step-id");
    if (!sceneId || !stepId) return;

    fetch(`/films/api/scene_status_summary/${sceneId}/${stepId}`)
      .then(res => res.json())
      .then(data => {
        if (!Array.isArray(data) || data.length === 0) return;
        const labels = data.map(d => d.label);
        const values = data.map(d => d.value);
        const colors = data.map(d => d.color);
        window.renderPieChart(`scene-chart-${sceneId}-${stepId}`, labels, values, colors);
      })
      .catch(err => console.error(`Chart error for scene ${sceneId} step ${stepId}:`, err));
  });

  // Filter Scenes Based on Selected Steps (with Chart Visibility)
  function toggleColumnVisibility(stepId, isVisible) {
    const cells = document.querySelectorAll(`[data-step-id="${stepId}"]`);
    cells.forEach(cell => {
      cell.style.display = isVisible ? "inline-block" : "none";
    });
  }

  // Set up the initial step filters
  const checkboxes = document.querySelectorAll("#scene-filter-form input[type=checkbox]");

  // Set all checkboxes to checked by default
  checkboxes.forEach(cb => {
    cb.checked = true;
    toggleColumnVisibility(cb.dataset.stepId, true);
  });

  // Attach event listeners for live filtering
  checkboxes.forEach(cb => {
    cb.addEventListener("change", () => {
      toggleColumnVisibility(cb.dataset.stepId, cb.checked);
    });
  });

  // Attach Event Listeners for Bulk Actions
  const allStepsButton = document.getElementById('show-all-steps');
  const artistStepsButton = document.getElementById('show-artist-steps');

  if (allStepsButton) {
    allStepsButton.addEventListener("click", (event) => {
      event.preventDefault();
      checkboxes.forEach(cb => {
        cb.checked = true;
        toggleColumnVisibility(cb.dataset.stepId, true);
      });
    });
  }

  if (artistStepsButton) {
    artistStepsButton.addEventListener("click", (event) => {
      event.preventDefault();
      checkboxes.forEach(cb => {
        const stepName = cb.dataset.stepName || "";
        const isArtistStep = !stepName.toLowerCase().includes("fb");
        cb.checked = isArtistStep;
        toggleColumnVisibility(cb.dataset.stepId, isArtistStep);
      });
    });
  }

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

  document.querySelectorAll("canvas[id^='scene-chart-']").forEach(canvas => {
    const sceneId = canvas.dataset.sceneId;
    const stepId = canvas.dataset.stepId;
    const chartId = canvas.id;

    fetch(`/films/api/scene_status_summary/${sceneId}/${stepId}`)
      .then(res => res.json())
      .then(data => {
        if (!Array.isArray(data) || data.length === 0) return;

        const ctx = canvas.getContext('2d');

        // 🧼 Destroy existing chart if it exists
        if (window.sceneCharts[chartId]) {
          window.sceneCharts[chartId].destroy();
        }

        setTimeout(() => {
          const chart = new Chart(ctx, {
            type: "pie",
            data: {
              labels: data.map(d => d.label),
              datasets: [{
                data: data.map(d => d.value),
                backgroundColor: data.map(d => d.color)
              }]
            },
            options: {
              responsive: true,
              maintainAspectRatio: true,
              plugins: {
                legend: { display: false }
              }
            }
          });

          window.sceneCharts[chartId] = chart;
        }, 50); // Wait 50ms to allow DOM layout to stabilize
        

        // 💾 Save it for next time
        window.sceneCharts[chartId] = chart;
      });
  });
  
  


});

function confirmDeleteScene(sceneId) {
  Swal.fire({
    title: 'Are you sure?',
    text: "This will permanently delete the scene and all its related data.",
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#d33',
    cancelButtonColor: '#3085d6',
    confirmButtonText: 'Yes, delete it!',
    cancelButtonText: 'Cancel'
  }).then((result) => {
    if (result.isConfirmed) {
      // Submit the hidden form to actually delete the scene
      document.getElementById(`delete-scene-form-${sceneId}`).submit();
    }
  });
}

function markSceneLayoutDone(button) {
  const sceneId = button.dataset.sceneId;
  const loginName = button.dataset.loginName;

  Swal.fire({
    title: 'Mark scene Layout done?',
    text: "This unlocks per-shot Layout for every shot in this scene. No instructor approval is required for this step.",
    icon: 'question',
    showCancelButton: true,
    confirmButtonColor: '#15803d',
    cancelButtonColor: '#3085d6',
    confirmButtonText: 'Yes, mark it done',
    cancelButtonText: 'Cancel'
  }).then((result) => {
    if (!result.isConfirmed) return;

    fetch('/classes/api/launcher/capstone/scene-layout/complete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scene_id: sceneId, login_name: loginName })
    })
      .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) {
          Swal.fire('Error', data.error || 'Could not mark Layout done.', 'error');
          return;
        }
        Swal.fire('Done', 'Scene Layout marked done.', 'success');
      })
      .catch(() => {
        Swal.fire('Error', 'Could not reach Shot Tracker.', 'error');
      });
  });
}