// edit_layout_config.js
// Phase 5 addendum: scene-scoped Layout config editor (asset assignment +
// per-shot Camera Framing). Two independent save actions matching the
// two independent, staggered lock boundaries on the backend
// (films_routes.py: save_scene_layout_assets / save_shot_camera_framing) —
// there is no single "save everything" button because scene assets and a
// given shot's framing can lock at different times.

document.addEventListener('DOMContentLoaded', () => {
  const saveAssetsBtn = document.getElementById('save-scene-assets-btn');
  if (saveAssetsBtn) {
    saveAssetsBtn.addEventListener('click', saveSceneAssets);
  }

  const unlockSceneBtn = document.getElementById('unlock-scene-assets-btn');
  if (unlockSceneBtn) {
    unlockSceneBtn.addEventListener('click', unlockSceneAssets);
  }

  document.querySelectorAll('.camera-framing-select').forEach((select) => {
    select.addEventListener('change', () => saveCameraFraming(select));
  });

  document.querySelectorAll('.unlock-shot-framing-btn').forEach((btn) => {
    btn.addEventListener('click', () => unlockShotCameraFraming(btn));
  });
});

function saveSceneAssets() {
  const assets = {};
  document.querySelectorAll('#scene-asset-categories div[data-category]').forEach((container) => {
    const category = container.dataset.category;
    const selected = Array.from(container.querySelectorAll('.scene-asset-checkbox:checked'))
      .map((cb) => parseInt(cb.value, 10));
    assets[category] = selected;
  });

  fetch(`/films/${window.filmId}/scenes/${window.sceneId}/layout-config/assets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ assets })
  })
    .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
    .then(({ ok, data }) => {
      if (!ok) {
        Swal.fire('Error', data.error || 'Could not save asset assignments.', 'error');
        return;
      }
      Swal.fire({
        icon: 'success',
        title: 'Saved',
        text: 'Scene asset assignments saved.',
        timer: 1500,
        showConfirmButton: false
      });
    })
    .catch(() => {
      Swal.fire('Error', 'Network error while saving asset assignments.', 'error');
    });
}

function unlockSceneAssets() {
  Swal.fire({
    title: 'Unlock scene asset config?',
    text: 'This also reopens the scene-Layout-done gate that lets shot-level Layout be created. Shots that already copied in the scene Layout are not affected — only new shot-Layout creation and further scene asset edits reflect what you change from here on.',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#c2410c',
    cancelButtonColor: '#3085d6',
    confirmButtonText: 'Yes, unlock',
    cancelButtonText: 'Cancel'
  }).then((result) => {
    if (!result.isConfirmed) return;

    fetch(`/films/${window.filmId}/scenes/${window.sceneId}/layout-config/unlock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
      .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) {
          Swal.fire('Error', data.error || 'Could not unlock scene asset config.', 'error');
          return;
        }
        if (data.shots_exist) {
          Swal.fire({
            icon: 'info',
            title: 'Unlocked',
            text: 'Scene asset config unlocked. Note: this scene already has shots — editing assets now will not retroactively change any shot Layout files already created.'
          }).then(() => location.reload());
        } else {
          location.reload();
        }
      })
      .catch(() => {
        Swal.fire('Error', 'Network error while unlocking scene asset config.', 'error');
      });
  });
}

function unlockShotCameraFraming(button) {
  const shotId = button.dataset.shotId;

  Swal.fire({
    title: 'Unlock this shot\'s Camera Framing?',
    text: 'This also un-marks this shot\'s Layout as approved, since they share the same lock — that reopens Layout for this shot in the dashboard/Maya flow too, not just this dropdown. An Animation file already created for this shot is not affected.',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#c2410c',
    cancelButtonColor: '#3085d6',
    confirmButtonText: 'Yes, unlock',
    cancelButtonText: 'Cancel'
  }).then((result) => {
    if (!result.isConfirmed) return;

    fetch(`/films/${window.filmId}/scenes/${window.sceneId}/layout-config/shots/${shotId}/unlock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
      .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) {
          Swal.fire('Error', data.error || 'Could not unlock Camera Framing.', 'error');
          return;
        }
        if (data.animation_started) {
          Swal.fire({
            icon: 'info',
            title: 'Unlocked',
            text: 'Camera Framing unlocked. Note: Animation has already started for this shot — it is not affected by this unlock.'
          }).then(() => location.reload());
        } else {
          location.reload();
        }
      })
      .catch(() => {
        Swal.fire('Error', 'Network error while unlocking Camera Framing.', 'error');
      });
  });
}

function saveCameraFraming(select) {
  const shotId = select.dataset.shotId;
  const camera_framing = select.value;

  if (!camera_framing) return;

  fetch(`/films/${window.filmId}/scenes/${window.sceneId}/layout-config/shots/${shotId}/camera-framing`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ camera_framing })
  })
    .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
    .then(({ ok, data }) => {
      if (!ok) {
        Swal.fire('Error', data.error || 'Could not save Camera Framing.', 'error');
        return;
      }
      Swal.fire({
        icon: 'success',
        title: 'Saved',
        text: `Camera Framing set to ${data.camera_framing}.`,
        timer: 1200,
        showConfirmButton: false
      });
    })
    .catch(() => {
      Swal.fire('Error', 'Network error while saving Camera Framing.', 'error');
    });
}
