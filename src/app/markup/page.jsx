"use client";

export const dynamic = "force-dynamic";


import { useEffect, useState, useRef, useCallback } from "react";
import VideoPlayer from "../../components/VideoPlayer";
import DrawingTools from "../../components/DrawingTools";
import SideBar from "../../components/SideBar";
import OnionSkinSettings from "../../components/OnionSkinSettings";
import CompareVersionSettings from "../../components/CompareVersionSettings";
import Swal from "sweetalert2";


// ✅ NOW define this
const getSessionStorage = () => {
  if (typeof window === "undefined") return null;
  return window.sessionStorage;
};

console.log("🟢 page.jsx: top-level code executing");


// ✅ Handles both localhost dev and deployed /markup/ path
const API_BASE_URL =
  process.env.NODE_ENV === "development"
    ? "http://localhost:5000"
    : (typeof window !== "undefined" ? window.location.origin : "");

console.log("🌐 API_BASE_URL =", API_BASE_URL, "mode =", process.env.NODE_ENV);


// 🔁 Single bridge: push options to global + notify React (if bound)
function pushStatusOptions(opts) {
  const options = Array.isArray(opts) ? opts : [];

  if (typeof window !== "undefined") {
    window.statusOptionsForStep = options;

    if (typeof window.refreshSceneStatusOptions === "function") {
      try {
        window.refreshSceneStatusOptions(options);
      } catch (e) {
        console.warn("refreshSceneStatusOptions threw:", e);
      }
    }
  }
}


export default function MarkupTool() {
  const [lastChangedGrade, setLastChangedGrade] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState("assignments");
  const [fileList, setFileList] = useState({ assignments: [], films: [] });
  const [selectedFile, setSelectedFile] = useState(null);
  const [showSceneModal, setShowSceneModal] = useState(false);
  const [scenes, setScenes] = useState([]);
  const [films, setFilms] = useState([]);
  const [steps, setSteps] = useState([]);
  const [selectedFilm, setSelectedFilm] = useState("");
  const [selectedScene, setSelectedScene] = useState("");
  const [selectedStep, setSelectedStep] = useState("");
  const [selectedSceneId, setSelectedSceneId] = useState("");
  const clearCanvasRef = useRef(() => {});
  const redrawCanvasRef = useRef(() => {});
  const [canvasKey, setCanvasKey] = useState(0);
  const [isDrawing, setIsDrawing] = useState(false);
  const [brushColor, setBrushColor] = useState("#ff0000");
  const [brushSize, setBrushSize] = useState(8);
  const [frameAnnotations, setFrameAnnotations] = useState({});
  const [currentFrame, setCurrentFrame] = useState(0);
  const [undoStack, setUndoStack] = useState([]);
  const [redoStack, setRedoStack] = useState([]);
  const [statusOptions, setStatusOptions] = useState([]);
  const [statusColors, setStatusColors] = useState({});
  const [currentStatus, setCurrentStatus] = useState("");
  const [selectedItem, setSelectedItem] = useState(null);
  const [selectedAssignment, setSelectedAssignment] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [thumbnailStatus, setThumbnailStatus] = useState(null);
  const [gradeStepNames, setGradeStepNames] = useState([]);
  const [gradeOptionsByStep, setGradeOptionsByStep] = useState({});
  const [annotations, setAnnotations] = useState({});
  const [noteInput, setNoteInput] = useState("");
  const [allShots, setAllShots] = useState([]);
  const [classPerm, setClassPerm] = useState(0);
  const [filmPerm, setFilmPerm] = useState(0);
  const [storyboardMode, setStoryboardMode] = useState(false);
  const [storyboardShots, setStoryboardShots] = useState([]);
  const [storyboardOptions, setStoryboardOptions] = useState([]);
  const [feedbackStepId, setFeedbackStepId] = useState(null);
  const [onionSkinConfig, setOnionSkinConfig] = useState({
    enabled: false,
    beforeCount: 4,
    afterCount: 4,
    beforeColor: "#0000ff",
    afterColor: "#34ec90ff"
  });
  const [compareConfig, setCompareConfig] = useState({
    enabled: false,
    color: "#ffa500"
  });
  const [compareVersions, setCompareVersions] = useState([]);
  const [compareVersion, setCompareVersion] = useState("");
  const [compareAnnotations, setCompareAnnotations] = useState({});


  // --- Step 1: hard separation between THUMB and SB ---

  function resetStoryboardState() {
    setStoryboardMode(false);
    setStoryboardShots([]);
    setStoryboardOptions([]);
    setFeedbackStepId(null);

    // 🔒 HARD reset globals
    window.storyboardMode = false;
    window.selectedStepCode = null;
  }

  function enterStoryboardMode(stepCode = "SB") {
    setStoryboardMode(true);

    // 🔒 Explicitly set globals
    window.storyboardMode = true;
    window.selectedStepCode = stepCode;
  }

  useEffect(() => {
    const handleHotkeys = (e) => {
      if (e.ctrlKey && e.key.toLowerCase() === "r") {
        e.preventDefault();
        document.querySelector("#startObsBtn")?.click();
      }

      if (e.ctrlKey && e.key.toLowerCase() === "s") {
        e.preventDefault();
        document.querySelector("#stopObsBtn")?.click();
      }
    };

    window.addEventListener("keydown", handleHotkeys);

    return () => {
      window.removeEventListener("keydown", handleHotkeys);
    };
  }, []);

  useEffect(() => {
    const storedSceneId = sessionStorage.getItem("lastSceneId");

    if (storedSceneId) {
      console.log("🔁 Restored scene_id for markup.js:", storedSceneId);
      window.scene_id = Number(storedSceneId);
      sessionStorage.removeItem("lastSceneId");
    }
  }, []);


  useEffect(() => {
    const handleError = (e) =>
      console.error("❌ Runtime error:", e.error || e.message);

    const handleRejection = (e) =>
      console.error("❌ Unhandled promise:", e.reason);

    window.addEventListener("error", handleError);
    window.addEventListener("unhandledrejection", handleRejection);

    return () => {
      window.removeEventListener("error", handleError);
      window.removeEventListener("unhandledrejection", handleRejection);
    };
  }, []);

  useEffect(() => {
    window.setCurrentStatus = setCurrentStatus;
  }, [setCurrentStatus]);

  useEffect(() => {
    window.markupData = frameAnnotations;
  }, [frameAnnotations]);

  useEffect(() => {
    window.markupNotes = noteInput;
  }, [noteInput]);

  useEffect(() => {
    fetch(`${API_BASE_URL}/review/get_permissions`, { credentials: "include" })
      .then(res => res.json())
      .then(data => {
        console.log("Permissions loaded:", data);
        setClassPerm(data?.classes || 0);
        setFilmPerm(data?.films || 0);
      })
      .catch(err => console.error("Failed to fetch permissions:", err));
  }, []);

  // 🔗 Bridge: SceneReviewSession pushes dropdown options here
  useEffect(() => {
    const bridge = (opts) => {
      console.log("[React] Received updated status options from SceneReviewSession:", opts);
      const list = Array.isArray(opts) ? opts : [];
      setStatusOptions(list);
      setStatusColors(window.statusColorByName || {}); // provided by sceneReviewSession.js
      setCurrentStatus(prev => prev || list[0] || "");
    };
    bridge.__owner = "react";
    window.refreshSceneStatusOptions = bridge;

    // If SRS set globals before we mounted, preload them
    if (Array.isArray(window.statusOptionsForStep) && window.statusOptionsForStep.length) {
      setStatusOptions(window.statusOptionsForStep);
      setStatusColors(window.statusColorByName || {});
      setCurrentStatus(prev => prev || window.statusOptionsForStep[0] || "");
    }

    return () => { window.refreshSceneStatusOptions = null; };
  }, []);


  // 🎨 Tint select + keep a visible swatch in sync with status color
  useEffect(() => {
    const el = document.getElementById("reviewStatus");
    if (!el) return;
    const color = (window.statusColorByName || {})[currentStatus] || "";
    el.style.borderColor = color || "";
    el.style.boxShadow = color ? `0 0 0 2px ${color}55 inset` : "";
  }, [currentStatus]);



  // ✅ Bridge global → React once SceneReviewSession loads
  useEffect(() => {
    console.log("🔗 Binding refreshSceneStatusOptions hook...");

    // Define the bridge function — SceneReviewSession.js will call this
    window.refreshSceneStatusOptions = (opts) => {
      console.log("🎯 [React] Received updated status options from SceneReviewSession:", opts);

      if (Array.isArray(opts) && opts.length > 0) {
        setStatusOptions(opts);
        setCurrentStatus((prev) => prev || opts[0]);
      } else {
        console.warn("⚠️ [React] Empty or invalid options received");
        setStatusOptions([]);
      }
    };

    // 🧩 Initialize immediately if SceneReviewSession already populated global variable
    if (window.statusOptionsForStep?.length) {
      console.log("💾 [React] Preloading from global:", window.statusOptionsForStep);
      setStatusOptions(window.statusOptionsForStep);
      setCurrentStatus((prev) => prev || window.statusOptionsForStep[0]);
    }

    // Cleanup
    return () => {
      console.log("🔌 Unbinding refreshSceneStatusOptions");
      window.refreshSceneStatusOptions = null;
    };
  }, []);



  // Load films for dropdown
  const loadFilms = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/review/films`);
      const data = await res.json();
      setFilms(data);
    } catch (err) {
      console.error("Failed to load films:", err);
    }
  };

  // Load scenes for selected film
  const loadScenes = async (filmId) => {
    try {
      const res = await fetch(`/review/films/${filmId}/scenes`);
      const data = await res.json();
      setScenes(data);
    } catch (err) {
      console.error("Failed to load scenes:", err);
    }
  };

  // Load steps for selected film
  const loadSteps = async (filmId) => {
    try {
      const res = await fetch(`/review/films/${filmId}/steps`);
      const data = await res.json();
      setSteps(data);
    } catch (err) {
      console.error("Failed to load steps:", err);
    }
  };


  function resolveShotIdFromFilename(item, allShots) {
    if (!item?.file_name || !Array.isArray(allShots) || !allShots.length) {
      console.warn("resolveShotIdFromFilename: missing filename or allShots");
      return null;
    }

    const match = item.file_name.match(/_(\d{3})_(\d{3})_/);
    if (!match) {
      console.warn("resolveShotIdFromFilename: no 3-digit pattern found");
      return null;
    }

    const sceneCode = parseInt(match[1], 10);
    const shotCode = parseInt(match[2], 10);
    const sceneId = parseInt(
      item.scene_id ??
      (typeof window !== "undefined" ? window.scene_id : 0),
      10
    );

    console.log("🔍 Matching shot_id from filename:", {
      sceneCode,
      shotCode,
      sceneId,
      totalShots: allShots.length,
    });

    const found = allShots.find((s) => {
      const sameScene =
        Number(s.scene_id) === sceneId ||
        Number(s.scene_number) === sceneCode;
      const sameShot =
        Number(s.shot_number) === shotCode ||
        String(s.shot_number).padStart(3, "0") === String(shotCode).padStart(3, "0");
      return sameScene && sameShot;
    });

    if (found) {
      console.log(`✅ Matched shot_id: ${found.id} for ${item.file_name}`);
      return found.id;
    }

    console.warn("❌ No matching shot_id found for", item.file_name);
    return null;
  }

  useEffect(() => {
    if (!showSceneModal) return;

    fetch(`${API_BASE_URL}/review/films`)
      .then((res) => res.json())
      .then((data) => {
        console.log("🎬 Loaded films for modal:", data);
        setFilms(data);
      })
      .catch((err) => console.error("❌ Failed to load films:", err));
  }, [showSceneModal]);

  async function saveCurrentStatus() {
    const sceneId =
      typeof window !== "undefined" ? window.scene_id : null;

    const shotId =
      typeof window !== "undefined" ? window.currentShotId : null;

    const stepId =
      typeof window !== "undefined" ? window.feedbackStepId : null;

    if (!shotId || !stepId || !sceneId) {
      console.warn("Missing ids for save:", {
        shot_id: shotId,
        step_id: stepId,
        scene_id: sceneId,
      });
      return;
    }
    setSaving(true);
    setSaveMsg("");
    try {
      const res = await fetch(`${API_BASE_URL}/review/update_scene_status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "shot",
          scene_id: Number(sceneId),
          shot_id: Number(shotId),
          step_id: Number(stepId),
          new_status: currentStatus,
        }),
      });
      const data = await res.json();

      // ✅ reflect server truth
      if (data?.verified_status) {
        setCurrentStatus(data.verified_status);
        // update our in-memory list so Next/Prev reflects it immediately
        try {
          const shotId = Number(window.currentShotId);
          if (Array.isArray(window.__allShotsRef__)) {
            const idx = window.__allShotsRef__.findIndex(s => Number(s.id) === shotId);
            if (idx >= 0) window.__allShotsRef__[idx].current_status = data.verified_status;
          }
        } catch { }
      }

      if (res.ok && data?.verified_status === currentStatus) {
        setSaveMsg("Saved ✓");
      } else if (res.ok) {
        setSaveMsg(`Saved → ${data?.verified_status || "?"}`);
      } else {
        setSaveMsg("Save failed");
        console.error("❌ Save error payload:", data);
      }
      setTimeout(() => setSaveMsg(""), 1500);
    } catch (err) {
      console.error("❌ Failed to update scene status:", err);
      setSaveMsg("Save failed");
      setTimeout(() => setSaveMsg(""), 2500);
    } finally {
      setSaving(false);
    }
  }

  async function loadStoryboardFeedback(sceneId, fileName) {
    if (!storyboardMode) return;
    if (!fileName) return;
    if (fileName.includes("_THUMB")) return;
    try {
      // ✅ Derive correct step code from filename
      let stepCode = "SB";
      if (fileName?.includes("_THUMB")) stepCode = "THUMB";
      else if (fileName?.includes("_SB")) stepCode = "SB";

      const res = await fetch(
        `/review/get_feedback_status/${sceneId}/${stepCode}`
      );
      const data = await res.json();

      if (!data || data.error) return;

      setStoryboardShots(data.statuses);
      setStoryboardOptions(data.options);
      setFeedbackStepId(data.feedback_step_id);

    } catch (err) {
      console.error("❌ Error loading storyboard feedback:", err);
    }
  }


  async function updateStoryboardStatus(shotId, stepId, newStatus) {
    const payload = {
      scene_id: Number(selectedSceneId),   // required
      shot_id: Number(shotId),             // required
      step_id: Number(stepId),             // required
      new_status: newStatus,               // required
      mode: "shot"                         // required for crossflow
    };

    console.log("📤 SB SEND:", payload);

    try {
      const res = await fetch(`${API_BASE_URL}/review/update_scene_status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      console.log("📥 SB REPLY:", data);

      // force refresh
      if (storyboardMode && selectedItem?.file_name?.includes("_SB")) {
        loadStoryboardFeedback(selectedSceneId, selectedItem.file_name);
      }




    } catch (err) {
      console.error("❌ SB error:", err);
    }
  }


  async function finalizeStoryboardReview() {
    if (!selectedSceneId) return;

    try {
      const res = await fetch(`/films/api/finalize_storyboard/${selectedSceneId}`, {
        method: "POST",
      });

      const data = await res.json();
      console.log("📥 Finalize SB:", data);

      if (data.error) {
        Swal.fire({
          icon: "error",
          title: "Error",
          text: data.error,
        });
        return;
      }

      // ⭐ Show success SweetAlert
      await Swal.fire({
        icon: "success",
        title: "Storyboard Review Saved!",
        text: "The storyboard has been marked as reviewed and the reviewed file has been created.",
        confirmButtonColor: "#3085d6",
        confirmButtonText: "OK",
      });

      // ⭐ Load the new _R movie
      if (data.reviewed_file_path) {
        const videoUrl = `${API_BASE_URL}/review/get_video?path=${encodeURIComponent(data.reviewed_file_path)}`;
        setSelectedFile(videoUrl);
      }

      // ⭐ Hard refresh (same behavior as assignment Save)
      if (typeof window !== "undefined") {
        window.location.reload();
      }

    } catch (err) {
      console.error("❌ Finalize storyboard:", err);

      Swal.fire({
        icon: "error",
        title: "Oops!",
        text: "Something went wrong while saving the storyboard review.",
      });
    }
  }



  // page.jsx — inside handleStartSceneSession (or startSceneReview)
  const handleStartSceneSession = async () => {
    if (!selectedSceneId) return;
    try {
      const step = selectedStep || "LAY";
      if (typeof window !== "undefined") {
        window.selectedStepCode = step;
      }
      window.scene_id = Number(selectedSceneId);
      window.selectedSceneId = Number(selectedSceneId);
      window.selectedFilmName =
        (films.find(f => String(f.id) === String(selectedFilm))?.name) || "";
      window.selectedSceneNum =
        (scenes.find(s => String(s.id) === String(selectedSceneId))?.scene_number) || "";

      const res = await fetch(
        `${API_BASE_URL}/review/films/scenes/${selectedSceneId}/shots?step=${encodeURIComponent(step)}`
      );
      const data = await res.json();

      // ✅ PUT THIS LINE RIGHT HERE:
      window.__allShotsRef__ = Array.isArray(data) ? data : [];

      window.API_BASE_URL = API_BASE_URL;

      console.log("🎬 Scene Shots for session:", data);
      setShowSceneModal(false);

      if (typeof window !== "undefined") {
        import("./sceneReviewSession").then(mod => {
          mod.initSceneReviewSession({
            setSelectedFile,
            allShots,
            selectedFile,
            currentStepPrefix
          });
        });
      }
    } catch (err) {
      console.error("❌ Failed to start session:", err);
    }
  };



  // 🩵 Restore last scene_id after page reload
  useEffect(() => {
    const storage = getSessionStorage();
    const savedSceneId = storage?.getItem("lastSceneId");

    if (!savedSceneId) return;

    console.log("🔁 Restored lastSceneId:", savedSceneId);

    // ONLY update if nothing is selected yet
    setSelectedItem(prev => {
      if (prev && prev.scene_id) return prev;

      return { scene_id: Number(savedSceneId) };
    });

    // OPTIONAL: only call this if it exists AND hasn't been set yet
    if (typeof setCurrentSceneId === "function") {
      setCurrentSceneId(prev => prev || Number(savedSceneId));
    }

  }, []);


  useEffect(() => {
    fetch(`${API_BASE_URL}/review/get_all_step_names?prefix=Grade`)
      .then((res) => res.json())
      .then((data) => {
        console.log("✅ All Grade Step Names:", data.step_names);
        setGradeStepNames(data.step_names);
      })
      .catch((err) => console.error("❌ Failed to load step names", err));
  }, []);

  useEffect(() => {
    fetch(`${API_BASE_URL}/review/api/assignment-review-files`)
      .then(async (res) => {
        if (!res.ok) {
          // Grab raw text in case it's an HTML error page
          const text = await res.text();
          console.error("❌ Server returned error:", text);
          throw new Error("Failed to fetch assignment files.");
        }
        return res.json();
      })
      .then((data) => {
        console.log("✅ Sidebar Files:", data);

        const sidebarData = {
          assignments: data.assignments || [],
          all_assignments: data.all_assignments || {},
          films: data.films || [],
          films_reviewed: data.films_reviewed || [],
        };

        // ✅ Safely expose globally for sceneReviewSession (only after it's fetched)
        window.sidebarFiles = sidebarData;

        setFileList(sidebarData);
      })

      .catch((error) => {
        console.error("❌ Failed to load sidebar files:", error.message);
      });
  }, []);
  
  useEffect(() => {
    if (isDrawing) return;
    setNoteInput(frameAnnotations[currentFrame]?.note || "");
  }, [currentFrame, frameAnnotations, isDrawing]);


  useEffect(() => {
    if (!selectedItem) return;

    if (selectedItem.type === "assignment" && selectedItem.individual_assignment_id) {
      fetchAssignmentStatus(selectedItem.individual_assignment_id);
    }

    if (
      selectedItem.type === "film" &&
      /_R\.(webm|png|mov|mp4)$/i.test(selectedItem.file_path)
    ) {
      setFrameAnnotations({}); 
      const jsonPath = selectedItem.file_path.replace(/_R\.(webm|png|mov|mp4)$/i, "_R.json");
      fetch(`${API_BASE_URL}/review/get_annotation_file?path=${encodeURIComponent(jsonPath)}`)
        .then((res) => {
          if (!res.ok) {
            if (res.status === 404) {
              console.info("ℹ️ No fallback annotations for this film.");
              return null;
            }
            throw new Error(`HTTP ${res.status}`);
          }
          return res.json();
        })
        .then((data) => {
          if (data && typeof data === "object") {
            setFrameAnnotations(data);
            clearCanvasRef.current?.();
            redrawCanvasRef.current?.();
          }
        })
        .catch((err) => console.warn("❌ Fallback annotation load failed:", err));
    }
  }, [selectedItem]);
  
  const saveNote = () => {
    setFrameAnnotations((prev) => {
      const current = typeof prev[currentFrame] === "object" && !Array.isArray(prev[currentFrame])
        ? prev[currentFrame]
        : {};
      return {
        ...prev,
        [currentFrame]: {
          ...current,
          note: noteInput,
          strokes: current.strokes || [],
        },
      };
    });
    

    Swal.fire({
      toast: true,
      icon: "success",
      title: "Note saved!",
      position: "bottom-end",
      showConfirmButton: false,
      timer: 1200,
      timerProgressBar: true,
    });
  };
  
  const removeFileFromList = (filePath) => {
    setFileList(prev => {
      const remove = (arr) => arr?.filter(f => f.file_path !== filePath);
      return {
        ...prev,
        assignments: remove(prev.assignments),
        films: remove(prev.films),
        films_reviewed: remove(prev.films_reviewed),
        all_assignments: Object.fromEntries(
          Object.entries(prev.all_assignments || {}).map(([k, v]) => [k, remove(v)])
        )
      };
    });
  };
  

  function getUpdateMode(item, status) {
    if (!item) return "scene";
    if (item.shot_id && ["FB Layout", "FB Animation", "FB Lighting"].includes(status.step_name)) {
      return "shot";
    }
    if (item.isSB) return "sb";
    return "scene";
  }
  
  const handleGradeChange = async (step_id, new_status, statusMeta) => {
    try {
      if (!selectedItem) {
        console.warn("⚠️ No selectedItem found; skipping update.");
        return;
      }

      // 🧠 --- Resolve shot_id early and correctly ---
      let shotId = selectedItem?.shot_id ?? null;

      // 1️⃣ Try to resolve from filename if missing
      if (!shotId && selectedItem?.file_name) {
        const match = selectedItem.file_name.match(/_(\d{3})_(\d{3})_/);
        if (match) {
          const sceneNum = match[1];
          const shotNum = match[2];
          console.log(`🧩 Resolving shot_id → scene:${sceneNum} shot:${shotNum}`);

          const found = loadedShots?.find(
            (s) =>
              String(s.scene_number).padStart(3, "0") === sceneNum &&
              String(s.shot_number).padStart(3, "0") === shotNum
          );

          if (found) {
            shotId = found.id;
            console.log(`✅ Found shot_id = ${shotId} for ${selectedItem.file_name}`);
            setSelectedItem((prev) => ({ ...prev, shot_id: shotId }));
          } else {
            console.error("❌ Could not find shot_id match for", selectedItem.file_name);
            return;
          }
        } else {
          console.error("❌ Could not parse shot_id from filename");
          return;
        }
      }

      // 2️⃣ Fallback to loadedShots by comparing scene_number/shot_number fields
      if (!shotId && selectedItem?.scene_number && selectedItem?.shot_number) {
        const found = loadedShots?.find(
          (s) =>
            String(s.scene_number).padStart(3, "0") ===
            String(selectedItem.scene_number).padStart(3, "0") &&
            String(s.shot_number).padStart(3, "0") ===
            String(selectedItem.shot_number).padStart(3, "0")
        );
        if (found) {
          shotId = found.id;
          console.log(`✅ Matched shot_id via numbers: ${shotId}`);
          setSelectedItem((prev) => ({ ...prev, shot_id: shotId }));
        }
      }

      // ❌ Still nothing? Bail cleanly
      if (!shotId) {
        console.error("❌ No valid shot_id found — cannot proceed with update.");
        console.log("SelectedItem:", selectedItem);
        return;
      }

      // 🧭 --- Step direction logic (FB vs main) ---
      const isMarkup =
        typeof window !== "undefined" &&
        window.location.pathname.includes("/markup");
      const targetStepId = isMarkup
        ? (statusMeta?.display_step_id ?? step_id)   // Markup (FB step)
        : (statusMeta?.update_step_id ?? step_id);   // Manual/Maya (main step)

      // --- Build payload ---
      const payload = {
        scene_id:
          selectedItem.scene_id ||
          (typeof window !== "undefined" ? window.scene_id : null),
        step_id: targetStepId,
        new_status,
        shot_id: shotId,
        mode: "shot",
      };

      console.log("📤 Sending scene status update:", payload);

      console.log("🎬 [UI] Sending dropdown update:", {
        url: `${API_BASE_URL}/review/update_scene_status`,
        payload
      });

      // --- POST to Flask ---
      const res = await fetch(`${API_BASE_URL}/review/update_scene_status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data?.error || "Update failed");

      console.log("✅ Scene status update result:", data);

      // --- Sync UI instantly ---
      const linkedIds = data?.linked_step_ids || [];
      const allIds = [step_id, targetStepId, ...linkedIds].filter(Boolean);

      setSelectedItem((prev) => {
        const prevStatuses = Array.isArray(prev?.statuses)
          ? [...prev.statuses]
          : [];

        const updated = prevStatuses.map((s) =>
          allIds.includes(s.step_id) ? { ...s, status: new_status } : s
        );

        allIds.forEach((id) => {
          if (!updated.some((s) => s.step_id === id)) {
            updated.push({ step_id: id, status: new_status });
          }
        });

        console.log("🧩 UI synced steps:", allIds, "→", new_status);

        return {
          ...prev,
          shot_id: shotId,
          statuses: updated,
        };
      });
    } catch (err) {
      console.error("❌ handleGradeChange error:", err);
    }
  };


  
  const handleClearAll = useCallback(() => {
    Swal.fire({
      title: "Clear ALL Markups?",
      text: "This will remove all annotations from every frame. This action cannot be undone.",
      icon: "warning",
      showCancelButton: true,
      confirmButtonColor: "#d33",
      cancelButtonColor: "#555",
      confirmButtonText: "Yes, clear all"
    }).then((result) => {
      if (result.isConfirmed) {
        console.log("🧨 Clearing all markups...");
        setFrameAnnotations({});
        setUndoStack([]);
        setRedoStack([]);
        setCurrentFrame(1);
        clearCanvasRef.current?.();
      } else {
        console.log("✅ Clear All cancelled");
      }
    });
  }, []);
  
  
  const fetchAssignmentStatus = (assignmentId) => {
    if (!assignmentId) {
      console.error("❌ Missing individual_assignment_id in fetchAssignmentStatus");
      return;
    }

    fetch(`${API_BASE_URL}/review/get_assignment_status?id=${assignmentId}`)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
      })
      .then((data) => {
        console.log("✅ Fetched Assignment Status:", data);
        if (!Array.isArray(data.statuses)) {
          console.warn("❌ Expected array of statuses but got:", data);
          return;
        }

        // ✅ Update selectedItem with the new statuses
        setSelectedAssignment((prev) => {
          if (!prev) {
            console.warn("⚠️ No selectedItem to update.");
            return null;
          }

          const updated = {
            ...prev,
            statuses: Array.isArray(data.statuses) ? data.statuses : []
          };

          setSelectedItem(updated); // 🔧 Sync both states
          return updated;
        });
        
      })
      .catch((error) => {
        console.error("❌ Error fetching assignment status:", error);
      });
  };
  

  useEffect(() => {
    if (!selectedItem?.statuses) return;
    const fetchAllGradeOptions = async () => {
      const map = {};
      for (const status of selectedItem.statuses) {
        try {
          // Prefer display_step_id if provided by backend
          const stepId = status.display_step_id || status.step_id;
          const res = await fetch(`${API_BASE_URL}/review/get_grade_options?step_id=${stepId}`);


          const data = await res.json();

          if (Array.isArray(data)) {
            // use the correct key (the one we requested)
            map[stepId] = data;
          }

        } catch (err) {
          console.error(`❌ Failed to fetch grades for step_id=${status.step_id}`, err);
        }
      }


      setGradeOptionsByStep(map);
      console.log("🧭 gradeOptionsByStep initialized →", map);
      console.log("🎬 Available step keys:", Object.keys(map));


      if (typeof window !== "undefined") {
        // 🟢 Expose globally so Scene Review can use it
        window.gradeOptionsByStep = map;

        // 🟢 Log which step we’re currently in
        console.log("🎬 Selected step for review:", window.selectedStepCode);

        // 🟢 Log if we actually have options for it
        if (window.selectedStepCode && map[window.selectedStepCode]) {
          window.statusOptionsForStep = map[window.selectedStepCode];
          console.log(
            "✅ Loaded status options for step:",
            window.selectedStepCode,
            window.statusOptionsForStep
          );
        } else {
          console.warn("⚠️ No status options found for step:", window.selectedStepCode);
        }
      }


    };
    fetchAllGradeOptions();
  }, [selectedItem?.statuses]);


  useEffect(() => {
    // 🚫 NEVER fetch shots in storyboard mode
    if (storyboardMode) return;

    // 🩵 use stored or global scene_id as fallback
    const sceneId =
      selectedItem?.scene_id ||
      (typeof window !== "undefined" ? window.scene_id : null);

    if (!sceneId || isNaN(sceneId)) {
      console.warn("🚫 Skipping shot fetch. Invalid scene_id:", sceneId);
      return;
    }


    const url = `${API_BASE_URL}/review/films/scenes/${sceneId}/shots`;

    fetch(url, { credentials: "include" })
      .then(async (res) => {
        if (!res.ok) {
          const text = await res.text();
          throw new Error(`❌ Shot fetch failed: ${res.status} - ${text}`);
        }
        return res.json();
      })
      .then((data) => {
        if (!Array.isArray(data)) {
          console.warn("⚠️ Expected array of shots, got:", data);
          return;
        }

        setAllShots(data);
        console.log("🎯 Loaded shots:", data);

        const shotMatch = selectedItem?.file_name?.match(/_\d{3}_(\d{3})_/);
        const shotCode = shotMatch ? shotMatch[1] : null;

        if (shotCode) {
          const found = data.find(
            (s) => s.scene_id === sceneId && s.shot_number === shotCode
          );
          const shot_id = found?.id || null;
          console.log("🎯 Resolved shot_id from file_name:", shot_id);

          setSelectedItem((prev) => ({
            ...prev,
            shot_id,
          }));
        }
      })
      .catch((err) => {
        console.error("❌ Failed to load shots:", err.message);
      });
  }, [selectedItem?.scene_id]);
  
  
  // 🆕 Scene Review Session initialization (safe retry wrapper)
  useEffect(() => {
    const tryInit = () => {
      if (allShots && allShots.length > 0) {
        console.log("🟢 Initializing Scene Review Session with", allShots.length, "shots");
        if (typeof window !== "undefined") {
          import("./sceneReviewSession").then(mod => {
            mod.initSceneReviewSession({
              setSelectedFile,
              allShots,
              selectedFile,
              currentStepPrefix
            });
          });
        }
        return true;
      }
      console.log("⏳ Waiting for allShots...");
      return false;
    };

    // Retry every 0.5s up to 10 times to ensure DOM + data exist
    let tries = 0;
    const timer = setInterval(() => {
      tries++;
      if (tryInit() || tries > 10) clearInterval(timer);
    }, 500);

    return () => clearInterval(timer);
  }, [allShots]);


  // 🔄 Re-fetch the review lists and reset the UI
  // Put this in the same component as handleSave
  const refreshMarkup = async () => {
    try {
      // ✅ Prefer your existing loader if you have one (use whatever you call on page mount)
      if (typeof loadReviewFiles === "function") {
        await loadReviewFiles();
      } else if (typeof initMarkup === "function") {
        await initMarkup();
      } else {
        // 🔁 Fallback: try a backend list endpoint ONLY IF you know it works
        // Change the URL below to YOUR real route (examples: /review/get_all_assignment_files, /review/list, etc.)
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/review/get_files_for_review`, {
          method: "GET",
          headers: { "Content-Type": "application/json" }
        });
        if (res.ok) {
          const data = await res.json();
          if (data?.files_to_review && typeof setReviewFiles === "function") {
            setReviewFiles([...data.files_to_review]); // ✅ new array reference
          }
          if (data?.all_files && typeof setAllFiles === "function") {
            // ✅ new object reference to trigger re-render
            setAllFiles({ ...data.all_files });
          }

        } else {
          console.warn("refreshMarkup: list endpoint returned", res.status);
        }
      }
    } catch (e) {
      console.warn("refreshMarkup: skipped list reload:", e?.message || e);
    } finally {
      // ✅ Always clear current selection / canvas / video
      if (typeof setSelectedItem === "function") setSelectedItem(null);
      if (typeof setSelectedAssignment === "function") setSelectedAssignment(null);
      if (typeof setAnnotations === "function") setAnnotations({});
      if (typeof setCurrentFrame === "function") setCurrentFrame(0);

      // ✅ Safe video cleanup guard
      if (typeof videoRef !== "undefined" && videoRef?.current) {
        try {
          videoRef.current.pause();
          videoRef.current.removeAttribute("src");
          videoRef.current.load?.();
        } catch (e) {
          console.warn("Video cleanup skipped:", e);
        }
      }

      // ✅ Safe clearCanvas guards
      if (typeof clearAll === "function") {
        try { clearAll(); } catch (e) { console.warn("clearAll skipped:", e); }
      }
      if (typeof clearCanvas === "function") {
        try { clearCanvas(); } catch (e) { console.warn("clearCanvas skipped:", e); }
      }

      // ✅ Only reset videoUrl if hook exists
      if (typeof setVideoUrl === "function") {
        try { setVideoUrl(null); } catch (e) { console.warn("setVideoUrl skipped:", e); }
      }
    }

  };

  const handleOpenPrevious = async () => {
    if (!selectedItem?.file_path) {
      alert("No file selected.");
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/review/get_previous_version`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          file_path: selectedItem.file_path
        }),
      });

      const data = await res.json();

      if (!data.success) {
        alert("No previous version found.");
        return;
      }

      const videoUrl = `${API_BASE_URL}/review/get_video?path=${encodeURIComponent(data.previous_path)}`;
      const url = `/markup?file=${encodeURIComponent(videoUrl)}&readonly=1`;

      if (typeof window !== "undefined") {
        window.open(url, "_blank");
      }

    } catch (err) {
      console.error("❌ Failed to open previous version:", err);
    }
  };

  // Cross-version onion skin: whenever the selected file changes, look up
  // which prior versions of this same shot were actually reviewed (only
  // those have a _R.json with annotations worth ghosting) and reset any
  // comparison left over from the previous file.
  useEffect(() => {
    setCompareVersions([]);
    setCompareVersion("");
    setCompareAnnotations({});
    setCompareConfig((prev) => ({ ...prev, enabled: false }));

    if (!selectedItem?.file_path) return;

    fetch(`${API_BASE_URL}/review/list_versions?file_path=${encodeURIComponent(selectedItem.file_path)}`)
      .then((res) => res.json())
      .then((data) => setCompareVersions(Array.isArray(data.versions) ? data.versions : []))
      .catch((err) => console.warn("❌ Could not load version list:", err));
  }, [selectedItem?.file_path]);

  const handleSelectCompareVersion = (versionStr) => {
    setCompareVersion(versionStr);

    if (!versionStr) {
      setCompareAnnotations({});
      return;
    }

    const entry = compareVersions.find((v) => String(v.version) === versionStr);
    if (!entry) return;

    fetch(`${API_BASE_URL}/review/get_annotation_file?path=${encodeURIComponent(entry.json_path)}`)
      .then((res) => (res.ok ? res.json() : {}))
      .then((data) => setCompareAnnotations(data && typeof data === "object" ? data : {}))
      .catch((err) => console.warn("❌ Could not load compare version annotations:", err));
  };

  const handleSave = async () => {
    const freshAnnotations = frameAnnotations;
    setAnnotations(freshAnnotations);

    if (!selectedItem || (!selectedItem.statuses && !selectedItem.isSB)) {
      Swal.fire({
        icon: "info",
        title: "Missing Info",
        text: "No assignment or statuses selected.",
      });
      return;
    }

    // Warn if no markups found, but still allow save
    if (Object.keys(freshAnnotations).length === 0) {
      const result = await Swal.fire({
        icon: "warning",
        title: "No Markups Found",
        text: "There are no markups. Do you still want to save the grades?",
        showCancelButton: true,
        confirmButtonText: "Yes, save it",
        cancelButtonText: "Cancel",
      });

      if (!result.isConfirmed) {
        console.log("🛑 User cancelled saving without markups.");
        return;
      }
    }

    setSaving(true);

    try {
      // ✅ Always send a force flag so backend updates grade even if nothing changed
      const payload = {
        file_path: selectedItem.file_path,
        annotations: freshAnnotations,
        is_film: selectedCategory === "films",
        individual_assignment_id: selectedItem.individual_assignment_id || null,
        grades: selectedItem.statuses || [], // existing grade data
        force_grade_update: true, // ✅ ensures backend re-grades
      };

      console.log("🚀 Save Payload:", payload);
      console.log("🎬 [UI] Posting to /review/save_annotations", {
        url: `${process.env.NEXT_PUBLIC_API_URL}/review/save_annotations`,
        payload
      });

      const favorite =
        typeof document !== "undefined"
          ? document.getElementById("favoriteCheckbox")?.checked || false
          : false;
      payload.favorite = favorite;

      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/review/save_annotations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || "Failed to save");
      }

      const result = await res.json();
      console.log("✅ Save successful:", result);

      // ✅ Update scene progress if this is a film
      const fileName = selectedItem.file_name || "";
      const isThumb = fileName.includes("_THUMB_");
      const isShotBased = !isThumb;
      // 🧩 make sure we send the freshest statuses (dropdown edits)
      const freshStatuses = selectedAssignment?.statuses || selectedItem?.statuses || [];
      selectedItem.statuses = JSON.parse(JSON.stringify(freshStatuses));

      console.log("🎬 [UI] Re-sending to /review/update_scene_status", {
        scene_id: selectedItem.scene_id,
        statuses: selectedItem.statuses
      });
      if (selectedCategory === "films" && selectedItem?.scene_id && selectedItem?.statuses?.length) {
        for (const gradingStatus of selectedItem.statuses) {
          await fetch(`${API_BASE_URL}/review/update_scene_status`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              scene_id: selectedItem.scene_id,
              step_id: gradingStatus.display_step_id ?? gradingStatus.step_id,
              new_status: gradingStatus.status,
              shot_id: selectedItem.shot_id || null,
              mode: selectedItem.isSB
                ? (selectedItem.shot_id ? "shot" : "sb")
                : "shot",
            }),
          })
            .then(res => res.json())
            .then(async res => {
              console.log("✅ Updated scene status", res);
              console.log("🔎 reload check → currentSceneId:", selectedItem?.scene_id);

              const safeSceneId = selectedItem?.scene_id || currentSceneId;
              console.log("🧩 using safeSceneId:", safeSceneId);

              if (typeof initMarkup === "function" && safeSceneId) {
                console.log("🔄 Reloading via initMarkup...");
                await initMarkup();
                console.log("✅ initMarkup reload done");
              } else if (typeof loadReviewFiles === "function" && safeSceneId) {
                console.log("🔄 Reloading via loadReviewFiles...");
                await loadReviewFiles();
                console.log("✅ loadReviewFiles reload done");
              } else {
                console.warn("⚠️ No reload function found — reloading sidebar manually...");
                try {
                  const res = await fetch(`${API_BASE_URL}/review/api/assignment-review-files`);
                  if (res.ok) {
                    const data = await res.json();
                    console.log("✅ Manually reloaded sidebar files:", data);
                    if (data?.films || data?.films_reviewed) {
                      setFileList({
                        assignments: data.assignments || [],
                        all_assignments: data.all_assignments || {},
                        films: data.films || [],
                        films_reviewed: data.films_reviewed || [],
                      });
                    }
                  } else {
                    console.warn("⚠️ Manual reload failed:", res.status);
                  }
                } catch (err) {
                  console.error("❌ Manual reload fetch error:", err);
                }
              }

            })
            .catch(err => console.error("❌ Failed to update scene status", err));
        }

        // ⭐ Mark the source file reviewed (_R) once this shot's status is
        // Approved -- get_films_for_review() buckets a film file into
        // "Reviewed Films" purely by checking for "_r." in the filename
        // (see get_files_for_review.py), so without this rename an
        // approved shot never leaves "Films to Review". Mirrors what the
        // Scene Review Session's own Save button already does
        // unconditionally; here it's gated on Approved since this button
        // saves grades for statuses that aren't final yet too (Retake, etc).
        const approvedNow = selectedItem.statuses.some(
          (s) => (s.status || "").trim().toLowerCase() === "approved"
        );
        if (approvedNow && selectedItem.file_path) {
          try {
            const favorite =
              typeof document !== "undefined"
                ? document.getElementById("favoriteCheckbox")?.checked || false
                : false;
            const renameRes = await fetch(`${API_BASE_URL}/review/save_reviewed`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ file_path: selectedItem.file_path, favorite }),
            });
            const renameJson = await renameRes.json();
            console.log("🏷️ Marked reviewed (_R):", renameJson);
          } catch (err) {
            console.error("❌ Failed to mark file reviewed (_R):", err);
          }
        }
      }

      Swal.fire({
        icon: "success",
        title: "Saved!",
        timer: 1000,
        showConfirmButton: false,
        timerProgressBar: true,
      }).then(() => {
        console.log("🔄 Hard reloading page after save...");

        if (selectedItem?.scene_id) {
          sessionStorage.setItem("lastSceneId", selectedItem.scene_id);
          console.log("💾 Stored lastSceneId:", selectedItem.scene_id);
        }

        if (typeof window !== "undefined") {
          window.location.reload();
        }
      });
    } catch (err) {
      console.error("❌ Save failed:", err);
      Swal.fire({
        icon: "error",
        title: "Save failed",
        text: err.message || "Something went wrong",
      });
    } finally {
      setSaving(false);
    }
  };




  const clearCurrentFrame = useCallback(() => {
    console.groupCollapsed("🧹 clearCurrentFrame");
    console.log("🧹 clearCurrentFrame function is INCLUDED in build");

    try {
      console.log("• currentFrame =", currentFrame);
      console.log("• keys before =", Object.keys(frameAnnotations));

      setFrameAnnotations((prev) => {
        const updated = structuredClone(prev || {});
        let entry = updated[currentFrame];
        console.log("• entry before =", entry);

        if (!entry) {
          console.warn("• nothing to clear (no entry for this frame)");
          return updated;
        }

        // Case 1: entry is array of strokes
        if (Array.isArray(entry)) {
          delete updated[currentFrame];
          console.log("• removed array entry (strokes only)");
        }
        // Case 2: entry is object with strokes and notes
        else if (typeof entry === "object") {
          delete updated[currentFrame];
          console.log("• removed object entry (cleared strokes + note)");
        }

        console.log("• keys after =", Object.keys(updated));
        return updated;
      });

      setUndoStack((prev) => {
        const out = prev.filter((i) => i.frame !== currentFrame);
        console.log("• undo pruned ->", out.length);
        return out;
      });
      setRedoStack((prev) => {
        const out = prev.filter((i) => i.frame !== currentFrame);
        console.log("• redo pruned ->", out.length);
        return out;
      });

      // clear visible canvas
      console.log("• calling clearCanvasRef.current()", typeof clearCanvasRef.current);
      clearCanvasRef.current?.();
      console.log("• calling redrawCanvasRef.current()", typeof redrawCanvasRef.current);
      redrawCanvasRef.current?.();

      if (!isDrawing) {
        setCanvasKey((k) => k + 1);
      }


      console.log("✅ clearCurrentFrame finished");
    } catch (err) {
      console.error("❌ clearCurrentFrame error:", err);
    } finally {
      console.groupEnd();
    }
  }, [currentFrame, frameAnnotations]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.__markupDebug = {
        clearCurrentFrame,
        get frame() { return currentFrame; },
        clearCanvasRef,
        redrawCanvasRef,
      };
    }
  }, [clearCurrentFrame, currentFrame]);

  const handleSetClearCanvas = useCallback((fn) => {
    clearCanvasRef.current = fn;
  }, []);

  const handleSetRedrawCanvas = useCallback((fn) => {
    redrawCanvasRef.current = fn;
  }, []);

  const undoLastChange = () => {
    if (!frameAnnotations[currentFrame] || frameAnnotations[currentFrame].length === 0) return;
    setFrameAnnotations((prev) => {
      const updatedAnnotations = structuredClone(prev);
      const lastStroke = updatedAnnotations[currentFrame]?.pop();
      if (!lastStroke) return prev;
      if (updatedAnnotations[currentFrame]?.length === 0) {
        delete updatedAnnotations[currentFrame];
      }
      setRedoStack((prevRedo) => [...prevRedo, { frame: currentFrame, stroke: lastStroke }]);
      return updatedAnnotations;
    });
    setUndoStack((prevUndo) => prevUndo.slice(0, -1));
    setTimeout(() => {
      clearCanvasRef.current?.();
      redrawCanvasRef.current?.();
    }, 0);
  };

  const redoLastChange = () => {
    if (redoStack.length === 0) return;
    const lastRedo = redoStack.pop();
    if (!lastRedo || !lastRedo.stroke) return;
    setFrameAnnotations((prev) => {
      const updatedAnnotations = { ...prev };
      if (!updatedAnnotations[lastRedo.frame]) updatedAnnotations[lastRedo.frame] = [];
      updatedAnnotations[lastRedo.frame].push(lastRedo.stroke);
      return updatedAnnotations;
    });
    setUndoStack((prevUndo) => [...prevUndo, lastRedo]);
    setTimeout(() => {
      clearCanvasRef.current?.();
      redrawCanvasRef.current?.();
    }, 10);
  };

  const startSceneReview = async (filmId, sceneId, stepCode) => {
    try {
      console.log("🚀 startSceneReview called with:", { filmId, sceneId, stepCode });

      // Store for later if needed
      window.currentStepPrefix = stepCode;

      // 🆕 Store global context for session (film/scene/step)
      window.selectedFilmName = films.find(f => f.id === Number(filmId))?.name || "";
      window.selectedSceneNum = scenes.find(s => s.id === Number(sceneId))?.scene_number || "";
      window.selectedStepCode = stepCode;
      window.scene_id = Number(sceneId);
      window.selectedSceneId = Number(sceneId);

      console.log("🌍 Global context set →", {
        filmName: window.selectedFilmName,
        sceneNum: window.selectedSceneNum,
        stepCode: window.selectedStepCode,
        scene_id: window.scene_id,
      });

      // 🎞️ Load all shots for this scene
      const res = await fetch(`${API_BASE_URL}/review/films/scenes/${sceneId}/shots`);
      const data = await res.json();

      console.log("🎬 Scene Shots for session:", data);

      // Initialize the Scene Review session
      initSceneReviewSession({
        setSelectedFile,
        allShots: data,
        currentStepPrefix: stepCode,
      });

      // ✅ Close the modal before initializing scene buttons
      setShowSceneModal(false);

      // 🟢 Once modal is closed, safely attach scene buttons
      setTimeout(() => {
        if (window.initSceneButtons) {
          console.log("🎯 Scene modal closed — triggering scene button setup...");
          window.initSceneButtons();
        } else {
          console.warn("⚠️ window.initSceneButtons not available yet");
        }
      }, 500);

    } catch (err) {
      console.error("❌ Failed to start review session:", err);
    }
  };
 

  useEffect(() => {
    if (!storyboardMode) return;
    if (!selectedSceneId) return;
    if (!selectedItem?.file_name) return;
    if (!selectedItem.file_name.includes("_SB")) return;

    loadStoryboardFeedback(selectedSceneId, selectedItem.file_name);
  }, [storyboardMode, selectedSceneId]);




  return (
    <div className="bg-gray-900 text-white min-h-screen w-full">
    <div className="flex h-screen overflow-hidden bg-gray-800 text-white">
      <SideBar
        apiBaseUrl={API_BASE_URL}
        fileList={fileList}
        classPerm={classPerm}
        filmPerm={filmPerm} 
        onFileDeleted={removeFileFromList}
        setSelectedAssignment={setSelectedAssignment}
        selectedCategory={selectedCategory}
        setSelectedCategory={setSelectedCategory}
        handleFileClick={(file, category = selectedCategory) => {
          console.log("📦 handleFileClick file object:", file);

          const videoUrl = `${API_BASE_URL}/review/get_video?path=${encodeURIComponent(file.file_path)}`;
          setSelectedFile(videoUrl);

          // 🖊️ Planning drawings (still images, DB-backed via planning_files)
          // — handled entirely separately from the video/assignment logic
          // below. A Planning set can have several current images per
          // individual_assignment_id, so annotations must be loaded per
          // exact file_path, NOT via /review/get_annotations?id=, which
          // returns whatever's newest for the whole assignment and would
          // leak one drawing's markup onto another.
          if (file.is_planning_drawing) {
            resetStoryboardState();
            setSelectedFile(videoUrl);

            setSelectedItem({
              ...file,
              type: "assignment",
              isSB: false,
              statuses: [],
            });
            setSelectedAssignment({
              ...file,
              assignment_name: file.file_name?.split("_")[0] || "Planning Drawing",
              student_name: "",
              isSB: false,
              statuses: [],
            });

            if (file.individual_assignment_id) {
              fetchAssignmentStatus(file.individual_assignment_id);
            }

            setFrameAnnotations({});
            const isReviewedDrawing = /_R\.(png|jpe?g)$/i.test(file.file_path);
            if (isReviewedDrawing) {
              const jsonPath = file.file_path.replace(/_R\.(png|jpe?g)$/i, "_R.json");
              fetch(`${API_BASE_URL}/review/get_annotation_file?path=${encodeURIComponent(jsonPath)}`)
                .then((res) => {
                  if (!res.ok) {
                    if (res.status === 404) return null;
                    throw new Error(`HTTP ${res.status}`);
                  }
                  return res.json();
                })
                .then((data) => {
                  if (data && typeof data === "object") {
                    setFrameAnnotations(data);
                    setCurrentFrame(1);
                    clearCanvasRef.current?.();
                    redrawCanvasRef.current?.();
                  }
                })
                .catch((err) => console.warn("❌ Could not load planning drawing annotations:", err));
            }

            return;
          }

          // 🎥 Video references (converted .webm uploads, DB-backed via
          // video_reference_files) — same per-file annotation isolation as
          // planning drawings above, for the same reason: a student can
          // have several reference clips on one assignment. Link-type
          // entries never reach here -- SideBar opens those in a new tab
          // instead of calling handleFileClick.
          if (file.is_video_reference) {
            resetStoryboardState();
            setSelectedFile(videoUrl);

            setSelectedItem({
              ...file,
              type: "assignment",
              isSB: false,
              statuses: [],
            });
            setSelectedAssignment({
              ...file,
              assignment_name: file.file_name?.split("_")[0] || "Video Reference",
              student_name: "",
              isSB: false,
              statuses: [],
            });

            if (file.individual_assignment_id) {
              fetchAssignmentStatus(file.individual_assignment_id);
            }

            setFrameAnnotations({});
            const isReviewedRef = /_R\.webm$/i.test(file.file_path);
            if (isReviewedRef) {
              const jsonPath = file.file_path.replace(/_R\.webm$/i, "_R.json");
              fetch(`${API_BASE_URL}/review/get_annotation_file?path=${encodeURIComponent(jsonPath)}`)
                .then((res) => {
                  if (!res.ok) {
                    if (res.status === 404) return null;
                    throw new Error(`HTTP ${res.status}`);
                  }
                  return res.json();
                })
                .then((data) => {
                  if (data && typeof data === "object") {
                    setFrameAnnotations(data);
                    setCurrentFrame(1);
                    clearCanvasRef.current?.();
                    redrawCanvasRef.current?.();
                  }
                })
                .catch((err) => console.warn("❌ Could not load video reference annotations:", err));
            }

            return;
          }

          // 🎞️ Detect Storyboard movie EARLY (e.g., testme_040_SB_v1.webm)
          const isStoryboard = file.file_name && /_\d{3}_SB_/i.test(file.file_name);

          if (isStoryboard) {
            resetStoryboardState();

            const sbSceneId = file.scene_id;
            let stepCode = "SB";
            if (file.file_name.includes("_THUMB")) stepCode = "THUMB";

            if (stepCode === "SB") {
              // 🧹 HARD reset anything from film/shot mode
              setSelectedItem(null);
              setSelectedAssignment(null);

              enterStoryboardMode("SB");
              setSelectedSceneId(sbSceneId);

              loadStoryboardFeedback(sbSceneId, file.file_name);
            }


            // THUMB never enters storyboardMode
            setSelectedFile(videoUrl);
            setSelectedItem({
              ...file,
              isSB: false,
              statuses: [],
            });

            return;
          }



          // 🎬 If not storyboard → normal behavior
          resetStoryboardState();


          const isAssignment = !!file.individual_assignment_id;

          let assignmentName = "UnknownAssignment";
          let studentName = "UnknownStudent";

          if (file.file_name) {
            const base = file.file_name.replace(/\.[^/.]+$/, "");
            const parts = base.split("_");
            if (parts.length >= 2) {
              assignmentName = parts[0].trim();
              studentName = parts[1].trim();
            }
          }

          setSelectedItem({
            ...file,
            type: isAssignment ? "assignment" : "film",
            isSB: false,
            statuses: [],
          });

          if (file.scene_id) {
            window.scene_id = file.scene_id;
          }

          setSelectedAssignment({
            ...file,
            assignment_name: assignmentName,
            student_name: studentName,
            isSB: false,
            statuses: [],
          });

          const isReviewed = file.file_path.includes("_R");

          // ===========================
          // 🟦 NORMAL THUMBNAILS + ASSIGNMENTS
          // ===========================
          if (file?.file_name?.endsWith(".mov")) {
            setThumbnailStatus(file.status || "Waiting for Student");
          }

          if (file.individual_assignment_id) {
            console.log("🔍 file object:", file);
            console.log("🧪 individual_assignment_id:", file?.individual_assignment_id);
            fetchAssignmentStatus(file.individual_assignment_id);

            setFrameAnnotations({});
            fetch(`${API_BASE_URL}/review/get_annotations?id=${file.individual_assignment_id}`)
              .then((res) => res.json())
              .then((data) => {
                const fromDb = data.annotations && Object.keys(data.annotations).length > 0;
                setFrameAnnotations(fromDb ? data.annotations : {});
                setCurrentFrame(1);
                clearCanvasRef.current?.();
                redrawCanvasRef.current?.();

                if (!fromDb && isReviewed) {
                  setFrameAnnotations({});
                  const jsonPath = file.file_path.replace(/_R\.(webm|png|mov|mp4)$/i, "_R.json");
                  fetch(`${API_BASE_URL}/review/get_annotation_file?path=${encodeURIComponent(jsonPath)}`)
                    .then((res) => {
                      if (!res.ok) {
                        if (res.status === 404 && file.file_path.includes("_R.")) {
                          console.info("ℹ️ No annotation file found — likely no notes/strokes.");
                          return null;
                        } else {
                          throw new Error(`HTTP ${res.status}`);
                        }
                      }
                      return res.json();
                    })
                    .then((data) => {
                      if (data && typeof data === "object") {
                        setFrameAnnotations(data);
                        setCurrentFrame(1);
                        clearCanvasRef.current?.();
                        redrawCanvasRef.current?.();
                      }
                    })
                    .catch((err) => console.warn("❌ Could not load fallback annotation:", err));
                }
              });
          } else if (isReviewed) {
            setFrameAnnotations({});
            const jsonPath = file.file_path.replace(/_R\.(webm|png|mov|mp4)$/i, "_R.json");
            fetch(`${API_BASE_URL}/review/get_annotation_file?path=${encodeURIComponent(jsonPath)}`)
              .then((res) => {
                if (!res.ok) {
                  if (res.status === 404 && file.file_path.includes("_R.")) {
                    console.info("ℹ️ No annotation file found — likely no notes/strokes.");
                    return null;
                  } else {
                    throw new Error(`HTTP ${res.status}`);
                  }
                }
                return res.json();
              })
              .then((data) => {
                if (data && typeof data === "object" && Object.keys(data).length > 0) {
                  setFrameAnnotations(data);
                  setTimeout(() => {
                    clearCanvasRef.current?.();
                    redrawCanvasRef.current?.();
                  }, 10);
                }
              })
              .catch((err) => console.warn("❌ Could not load fallback annotation:", err));

            if (file.individual_assignment_id) {
              console.log("🔍 file object:", file);
              console.log("🧪 individual_assignment_id:", file?.individual_assignment_id);
              fetchAssignmentStatus(file.individual_assignment_id);

              fetch(`${API_BASE_URL}/review/get_grade_options?assignment_id=${file.individual_assignment_id}`)
                .then((res) => res.json())
                .then((data) => {
                  const optionsByStep = {};
                  data.forEach((step) => {
                    optionsByStep[step.step_id] = step.options;
                  });
                  setGradeOptionsByStep(optionsByStep);
                });

              setSelectedAssignment({
                ...file,
                assignment_name: file.assignment_name || "UnknownAssignment",
                student_name: file.student_name || "UnknownStudent",
                isSB: false,
                statuses: [],
              });
            } else {
              setSelectedAssignment({
                ...file,
                assignment_name: file.assignment_name || "UnknownAssignment",
                student_name: file.student_name || "UnknownStudent",
                isSB: false,
                statuses: file.statuses || [],
              });
            }
          }

          // ============================================================
          // 🎞️ FILM SHOTS (ONLY WHEN *NOT* STORYBOARDS)
          // ============================================================
          if (category === "films" && !isStoryboard && !storyboardMode) {


            const isSB = file.file_name.includes("_SB_");

            // 🚫 Ensure storyboard files DO NOT run film logic
            if (isSB) {
              console.log("⛔ Skipping film/shot logic because this is a storyboard file.");
              return;
            }

            fetch(
              `${API_BASE_URL}/review/get_scene_status?scene_id=${file.scene_id}&file_name=${encodeURIComponent(file.file_name)}`
            )
              .then(async (res) => {
                if (!res.ok) {
                  const errorText = await res.text();
                  throw new Error(`Scene status fetch failed: ${res.status} - ${errorText}`);
                }
                return res.json();
              })
              .then((data) => {
                if (!data.display_step_id || !Array.isArray(data.options)) {
                  console.warn("❌ No grading step info returned for scene", data);
                  const fallback = {
                    ...file,
                    scene_id: file.scene_id || null,
                    shot_id: null,
                    statuses: [],
                    isSB,
                  };
                  setSelectedAssignment(fallback);
                  setSelectedItem(fallback);
                  return;
                }

                const shotMatch = file.file_name.match(/_(\d{3})_(\d{3})_/);
                const shotCode = shotMatch ? shotMatch[2] : null;

                const matchedShot = allShots.find(
                  (s) =>
                    String(s.scene_id) === String(data.scene_id || file.scene_id) &&
                    String(s.shot_number).padStart(3, "0") === String(shotCode).padStart(3, "0")
                );

                const updated = {
                  ...file,
                  scene_id: data.scene_id || file.scene_id || null,
                  shot_id: matchedShot?.id ?? file.shot_id ?? null,
                  statuses: [
                    {
                      step_id: data.update_step_id,
                      display_step_id: data.display_step_id,
                      step_name: data.step_name,
                      status: data.status,
                      options: data.options,
                    },
                  ],
                  isSB,
                };

                setSelectedAssignment(updated);
                setSelectedItem((prev) => ({
                  ...prev,
                  ...updated,
                  shot_id: updated?.shot_id ?? prev?.shot_id ?? null,
                }));
                setGradeOptionsByStep({ [data.step_id]: data.options });
              })
              .catch((err) => {
                console.error("❌ Failed to fetch scene status", err);

                const fallback = {
                  ...file,
                  scene_id: file.scene_id || null,
                  shot_id: file?.shot_id ?? null,
                  statuses: [
                    {
                      step_id: null,
                      step_name: "Unknown Step",
                      status: "Waiting",
                      options: [],
                    },
                  ],
                };

                setSelectedAssignment(fallback);
                setSelectedItem((prev) => ({
                  ...prev,
                  ...fallback,
                }));
              });
          }
        }}


      />



      {/* Main content layout */}
      <div
        className="flex-1 flex flex-col min-h-0 items-center justify-start bg-gray-700 p-2 overflow-y-auto"
        style={{ maxHeight: '100vh' }}
      >
        {selectedItem && !storyboardMode && (
          <div className="w-full p-4 bg-gray-900 text-white rounded-md mb-2 flex items-center justify-between">
            <div className="flex items-center space-x-6 overflow-x-auto">
              <h2 className="text-lg font-bold whitespace-nowrap">
                Reviewing: {selectedItem.file_name}
              </h2>
              {false ? (
                <div className="text-sm italic text-yellow-300 bg-gray-800 px-4 py-1 rounded-md">
                  📢 Please remember to update the status of each shot during approvals!
                </div>
              ) : (
                <>
                  {(() => {
                    return null;
                  })()}
                    {(() => {
                      const seen = new Set();
                      const uniqueStatuses = (selectedAssignment?.statuses || []).filter(s => {
                        if (seen.has(s.step_id)) return false;
                        seen.add(s.step_id);
                        return true;
                      });

                      return uniqueStatuses
                        .sort((a, b) => (a.order_num || 0) - (b.order_num || 0))
                        .map((status, idx) => (
                          <div key={`${status.step_id || "unknown"}-${idx}`} className="flex flex-col space-y-0">
                            <label className="text-sm font-semibold">{status.step_name}</label>
                            <select
                              value={status.status || ""}
                              onChange={async (e) => {
                                const newStatus = e.target.value;

                                // ✅ clone array and object so React sees a new reference
                                setSelectedAssignment((prev) => {
                                  const updated = prev.statuses.map((s, i) =>
                                    i === idx ? { ...s, status: newStatus } : s
                                  );
                                  return { ...prev, statuses: updated };
                                });

                                setLastChangedGrade({
                                  step_id: status.step_id,
                                  new_grade: newStatus,
                                });

                                // 📘 Assignments: update via /assignments/api/update-status (includes crossflow logic)
                                if (
                                  selectedCategory === "assignments" &&
                                  selectedAssignment?.individual_assignment_id &&
                                  status.step_id
                                ) {
                                  const payload = {
                                    individual_assignment_id: selectedAssignment.individual_assignment_id,
                                    step_id: status.step_id,
                                    current_status: newStatus,
                                  };

                                  console.log("📤 Sending assignment status update:", payload);

                                  try {
                                    const res = await fetch(`${API_BASE_URL}/assignments/api/update-status`, {
                                      method: "POST",
                                      headers: { "Content-Type": "application/json" },
                                      body: JSON.stringify(payload),
                                    });

                                    const json = await res.json();
                                    console.log("✅ Assignment status update result:", json);

                                    // 🔄 Immediately refresh all dropdowns after update
                                    if (selectedAssignment?.individual_assignment_id) {
                                      const refreshRes = await fetch(
                                        `${API_BASE_URL}/review/get_assignment_status?id=${selectedAssignment.individual_assignment_id}`
                                      );
                                      const refreshData = await refreshRes.json();

                                      if (Array.isArray(refreshData.statuses)) {
                                        setSelectedAssignment((prev) => ({
                                          ...prev,
                                          statuses: refreshData.statuses,
                                        }));
                                        setSelectedItem((prev) => ({
                                          ...prev,
                                          statuses: refreshData.statuses,
                                        }));
                                        console.log("🔁 Refreshed statuses after crossflow:", refreshData.statuses);
                                      }
                                    }
                                  } catch (err) {
                                    console.error("❌ Failed to update assignment status:", err);
                                  }
                                }

                                // 🎬 Films: keep existing scene update logic
                                if (
                                  selectedCategory === "films" &&
                                  selectedAssignment?.scene_id &&
                                  status.step_id
                                ) {
                                  // 🧩 Safely resolve shot_id no matter where it's stored
                                  const resolvedShotId =
                                    selectedAssignment.shot_id ||
                                    selectedAssignment.id ||
                                    selectedAssignment.shot?.id ||
                                    selectedItem?.shot_id ||
                                    selectedItem?.shot?.id ||
                                    null;

                                  const payload = {
                                    scene_id: selectedAssignment.scene_id,
                                    step_id: status.display_step_id ?? status.step_id,
                                    new_status: newStatus,
                                    shot_id: resolvedShotId,
                                    mode: "shot",
                                  };

                                  if (!resolvedShotId) {
                                    // 🧩 Special case — THUMB or FBTHUMB files (scene-level thumbnails)
                                    const fname = selectedAssignment?.file_name || "";
                                    if (fname.includes("_THUMB") || fname.includes("FBTHUMB")) {
                                      console.log("🎬 Detected THUMB file — updating scene-level status instead");

                                      try {
                                        const thumbPayload = {
                                          scene_id: selectedAssignment.scene_id,
                                          step_id: status.display_step_id ?? status.step_id,
                                          status: newStatus,
                                        };

                                        fetch(`/films/api/scene_progress/${thumbPayload.scene_id}/${thumbPayload.step_id}/update`, {
                                          method: "POST",
                                          headers: { "Content-Type": "application/json" },
                                          body: JSON.stringify(thumbPayload),
                                        })
                                          .then(r => r.json())
                                          .then(res => {
                                            console.log("✅ Scene-level THUMB update:", res);
                                          })
                                          .catch(err => {
                                            console.error("❌ Scene-level THUMB update failed:", err);
                                          });

                                      } catch (err) {
                                        console.error("❌ Exception while updating THUMB scene:", err);
                                      }

                                      return; // ✅ done — handled THUMB update
                                    }

                                    // 🧱 Otherwise, bail out normally for real missing shots
                                    console.warn(
                                      "⚠️ No valid shot_id found — skipping update entirely (not forcing mode=scene).",
                                      selectedAssignment
                                    );
                                    return;
                                  }


                                  console.log("📤 Sending scene status update:", payload);

                                  try {
                                    const res = await fetch(`${API_BASE_URL}/review/update_scene_status`, {
                                      method: "POST",
                                      headers: { "Content-Type": "application/json" },
                                      body: JSON.stringify(payload),
                                    });
                                    const json = await res.json();
                                    console.log("✅ Scene status update result:", json);

                                    // ⭐ Mark reviewed (_R) the moment a step is set to
                                    // Approved. This onChange -- not the Save button --
                                    // is what actually persists a film shot's status, and
                                    // it never syncs selectedItem/selectedAssignment
                                    // .statuses back into state, so a later Save click
                                    // can't reliably see "just got approved" from state.
                                    if (
                                      newStatus.trim().toLowerCase() === "approved" &&
                                      selectedAssignment?.file_path
                                    ) {
                                      try {
                                        const favorite =
                                          typeof document !== "undefined"
                                            ? document.getElementById("favoriteCheckbox")?.checked || false
                                            : false;
                                        const renameRes = await fetch(`${API_BASE_URL}/review/save_reviewed`, {
                                          method: "POST",
                                          headers: { "Content-Type": "application/json" },
                                          body: JSON.stringify({ file_path: selectedAssignment.file_path, favorite }),
                                        });
                                        const renameJson = await renameRes.json();
                                        console.log("🏷️ Marked reviewed (_R):", renameJson);
                                      } catch (err) {
                                        console.error("❌ Failed to mark file reviewed (_R):", err);
                                      }
                                    }
                                  } catch (err) {
                                    console.error("❌ Failed to update scene status:", err);
                                  }
                                }


                              }}
                              className="p-1 bg-gray-900 border border-gray-600 text-white rounded-md"
                              // ✅ Use FB step_id (display_step_id) for dropdown options
                              disabled={!gradeOptionsByStep?.[status.display_step_id ?? status.step_id]}
                            >
                              {(gradeOptionsByStep?.[status.display_step_id ?? status.step_id] || []).map((option) => {
                                // 🧠 Handle both string and object formats
                                const isObj = typeof option === "object" && option !== null;
                                const label = isObj ? option.name ?? option.value ?? "Unknown" : option;
                                const value = isObj ? option.value ?? option.name ?? label : option;
                                const color = isObj ? option.color ?? "#222" : "#222"; // fallback dark gray

                                return (
                                  <option
                                    key={value}
                                    value={value}
                                    style={{
                                      backgroundColor: color,
                                      color: "black",
                                      fontWeight: "bold",
                                    }}
                                  >
                                    {label}
                                  </option>
                                );
                              })}


                            </select>

                          </div>
                        ));
                    })()}


                </>
              )}

            </div>
            <button
              onClick={handleSave}
              disabled={saving || (!selectedItem.isSB && !selectedItem?.statuses?.every(s => s.status && s.status.trim() !== ""))}
              className={`px-4 py-1 rounded-md ${saving ? "bg-gray-500" : "bg-blue-500 hover:bg-blue-600"}`}
            >
              {saving ? "Saving..." : "Save"}
            </button>

            <button
              onClick={() => {
                if (!selectedItem?.file_path) return;

                const url = `${API_BASE_URL}/review/get_video?path=${encodeURIComponent(
                  selectedItem.file_path
                )}`;

                const a = document.createElement("a");
                a.href = url;
                a.download = selectedItem.file_name || "review.webm"; // forces download
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
              }}
              className="px-4 py-1 rounded-md bg-green-600 hover:bg-green-700 text-white ml-2"
            >
              Download
            </button>
            {selectedItem?.file_name?.includes("_SB_") && (
              <button
                onClick={() => {
                  if (!selectedItem?.file_path) return;

                  const url = `${API_BASE_URL}/review/get_video?path=${encodeURIComponent(
                    selectedItem.file_path
                  )}`;

                  const a = document.createElement("a");
                  a.href = url;
                  a.download = selectedItem.file_name; // forces save
                  document.body.appendChild(a);
                  a.click();
                  document.body.removeChild(a);
                }}
                className="px-4 py-1 rounded-md bg-purple-600 hover:bg-purple-700 text-white ml-2"
              >
                Download Storyboard
              </button>
            )}


            {/* ⭐ Favorite Checkbox */}
            <label className="flex items-center gap-2 ml-4 text-sm">
              <input
                type="checkbox"
                id="favoriteCheckbox"
                className="w-4 h-4 accent-yellow-400"
              />
              <span>Add to Favorites</span>
            </label>
          </div>
        )}


        {/* 🎬 Scene Review Mode Bar (hidden until Start Session) */}
        <div
          id="sceneReviewBar"
          className="hidden w-full mb-2 rounded-t-2xl shadow-lg border border-slate-700 bg-slate-900 text-gray-100 px-4 py-2 flex items-center justify-between"
        >
          {/* Left */}
          <div className="flex items-center gap-3">
            <span className="text-lg font-semibold text-blue-300">
              Scene 110 – Review Session
            </span>
            <span className="text-sm text-gray-400">(3 Shots)</span>
          </div>

          {/* Center Controls */}
          <div className="flex items-center gap-2">
            <button
              id="scenePrevBtn"
              className="bg-slate-800 hover:bg-slate-700 text-gray-200 px-3 py-1 rounded-lg text-sm"
            >
              ◀ Prev Shot
            </button>
            <button
              id="sceneNextBtn"
              className="bg-blue-600 hover:bg-blue-500 text-white px-3 py-1 rounded-lg text-sm"
            >
              ▶ Next Shot
            </button>
            <button
              id="sceneConcatBtn"
              className="bg-green-600 hover:bg-green-500 text-white px-3 py-1 rounded-lg text-sm"
            >
              ⏯ Make Combined Clip
            </button>
          </div>

          {/* Right */}
          <div className="flex items-center gap-3">
            {/* 🟢 Scene Review: Dynamic Status Dropdown */}
            <div className="flex items-center gap-2">
              {/* live color swatch for current status */}
              <span
                aria-hidden="true"
                className="inline-block w-3 h-3 rounded-full border border-gray-600"
                style={{ backgroundColor: (statusColors?.[currentStatus]) || "#444" }}
                title={currentStatus || "No status"}
              />
              <select
                id="reviewStatus"
                className="p-1 bg-gray-900 border border-gray-600 text-white rounded-md"
                value={currentStatus || ""}
                onChange={(e) => {
                  const newStatus = e.target.value;
                  setCurrentStatus(newStatus); // SRS sets this on Next/Prev; this handles manual change
                }}
              >
                {(statusOptions || []).map((label) => (
                  <option
                    key={label}
                    value={label}
                    // browsers often ignore option bg; border/swatch handle color UX
                    style={{ backgroundColor: statusColors?.[label] || undefined }}
                  >
                    {label}
                  </option>
                ))}
              </select>

              <button
                id="sceneSaveBtn"
                type="button"
                onClick={async () => {
                  await saveCurrentStatus(); // ✅ still update DB status first

                  console.log("💾 Scene Review Save triggered (_R + JSON beside file)");

                  try {
                    const currentVideoPath =
                      typeof window !== "undefined"
                        ? window.currentVideoPath || window.currentSceneVideoPath
                        : null;
                    if (!currentVideoPath) throw new Error("No active video path found.");

                    const normalizedPath = currentVideoPath.replace(/\//g, "\\");
                    const folder = normalizedPath.substring(0, normalizedPath.lastIndexOf("\\"));
                    const baseName = normalizedPath.substring(normalizedPath.lastIndexOf("\\") + 1);

                    console.log("🎯 Review Save Target Folder:", folder);
                    console.log("🎬 Base Name:", baseName);

                    // ⭐ Get checkbox value
                    const favorite =
                      typeof document !== "undefined"
                        ? document.getElementById("favoriteCheckbox")?.checked || false
                        : false;

                    const renameRes = await fetch(`${API_BASE_URL}/review/save_reviewed`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ file_path: normalizedPath, favorite }),
                    });

                    if (!renameRes.ok) throw new Error(`Rename failed: ${renameRes.status}`);

                    // 2️⃣ Save markups and notes (just like normal review)
                    const annotations =
                      typeof window !== "undefined" ? window.markupData || {} : {};

                    const notes =
                      typeof window !== "undefined" ? window.markupNotes || "" : "";


                    const jsonRes = await fetch(`${API_BASE_URL}/review/save_annotations`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({
                        file_path: normalizedPath,
                        annotations,
                        notes,
                        is_film: true,
                      }),
                    });

                    if (!jsonRes.ok) throw new Error(`Annotation save failed: ${jsonRes.status}`);


                    console.log("✅ Scene Review saved successfully (_R + JSON beside source)");

                    Swal.fire({
                      icon: "success",
                      title: "Scene Review Saved",
                      text: "Marked _R and saved all markups beside the original file.",
                      timer: 2000,
                      showConfirmButton: false,
                    });

                  } catch (err) {
                    console.error("❌ Failed to save Scene Review:", err);
                    Swal.fire("Error", "Failed to save Scene Review (_R + JSON).", "error");
                  }
                }}
                disabled={
                  saving ||
                  (typeof window !== "undefined" ? !window.currentShotId : true)
                }
                className="px-3 py-1 rounded-md bg-blue-600 disabled:opacity-50 hover:bg-blue-500 transition"
                title="Save the status of the current shot"
              >
                {saving ? "Saving…" : "Save"}
              </button>


              {saveMsg && (
                <span className="text-sm text-gray-300 ml-1 select-none">{saveMsg}</span>
              )}
            </div>


            <button
              id="sceneExitBtn"
              className="bg-red-700 hover:bg-red-600 text-white px-3 py-1 rounded-lg text-sm"
            >
              Exit Session ✖
            </button>
          </div>
        </div>

        {/* 🎬 Scene Selection Modal */}
        {showSceneModal && (
          <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center z-50">
            <div className="bg-gray-900 border border-gray-700 justify-center rounded-2xl shadow-2xl w-[400px] p-6">
              <h2 className="text-xl font-semibold text-white mb-4">Start Review Session</h2>

              {/* Film */}
              <label className="block text-gray-300 mb-1">Film</label>
              <select
                className="w-full mb-3 bg-gray-800 text-white p-2 rounded-lg"
                value={selectedFilm}
                onChange={(e) => {
                  const val = e.target.value;
                  setSelectedFilm(val);
                  loadScenes(val);
                  loadSteps(val);
                }}
              >
                <option value="">Select Film</option>
                {films.map((film) => (
                  <option key={film.id} value={film.id}>
                    {film.name}
                  </option>
                ))}
              </select>

              {/* Scene */}
              <label className="block text-gray-300 mb-1">Scene</label>
              <select
                className="w-full mb-3 bg-gray-800 text-white p-2 rounded-lg"
                value={selectedScene}
                onChange={(e) => setSelectedScene(e.target.value)}
              >
                <option value="">Select Scene</option>
                {scenes.map(s => (
                  <option key={s.id} value={s.id}>{s.scene_number}</option>
                ))}
              </select>

              {/* Step */}
              <label className="block text-gray-300 mb-1">Step</label>
              <select
                className="w-full mb-3 bg-gray-800 text-white p-2 rounded-lg"
                value={selectedStep}
                onChange={(e) => setSelectedStep(e.target.value)}
              >
                <option value="">Select Step</option>
                {steps.map(st => (
                  <option key={st.id} value={st.short_code}>
                    {st.step_name} ({st.short_code})
                  </option>
                ))}
              </select>

              {/* Buttons */}
              <div className="flex justify-end gap-3 mt-4">
                <button
                  className="bg-slate-700 hover:bg-slate-600 text-white px-3 py-1 rounded-lg"
                  onClick={() => setShowSceneModal(false)}
                >
                  Cancel
                </button>
                <button
                  id="startSceneReviewBtn"
                  className="bg-blue-600 hover:bg-blue-500 text-white px-3 py-1 rounded-lg"
                  onClick={() => {
                    console.log("🎬 Starting review for:", {
                      selectedFilm,
                      selectedScene,
                      selectedStep,
                    });
                    setShowSceneModal(false);
                    startSceneReview(selectedFilm, selectedScene, selectedStep); // next step hook
                  }}
                >
                  Start
                </button>
              </div>
            </div>
          </div>
        )}
        {/* 🎞️ Storyboard Review Section */}
        {storyboardMode && (
          <div className="mt-4 bg-gray-900 rounded-lg p-4 border border-gray-700 w-full max-w-4xl">
            <h2 className="text-lg font-bold text-white mb-4">Storyboard Review</h2>
            <div className="flex gap-3 mb-4">

              <button
                className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg"
                onClick={() => {
                  storyboardShots.forEach((shot) => {
                    updateStoryboardStatus(shot.shot_id, shot.step_id, "Approved");
                  });
                }}
              >
                Approve All
              </button>

              <button
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg"
                onClick={() => finalizeStoryboardReview()}
              >
                Save & Close Review
              </button>
              <button
                className="px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg"
                onClick={() => {
                  // Pull directly from the active video element
                  const video =
                    typeof document !== "undefined"
                      ? document.querySelector("video")
                      : null;

                  if (!video?.src) {
                    console.error("❌ No video src found for storyboard download");
                    return;
                  }

                  // video.src will already be /review/get_video?path=...
                  const a = document.createElement("a");
                  a.href = video.src;
                  a.download = "Storyboard.webm"; // browser will keep real name
                  document.body.appendChild(a);
                  a.click();
                  document.body.removeChild(a);
                }}
              >
                Download Storyboard
              </button>


            </div>


            {storyboardShots.length === 0 ? (
              <p className="text-gray-400">No shots found for this scene.</p>
            ) : (
              <div className="flex flex-wrap gap-3">

                {storyboardShots.map((shot) => (
                  <div
                    key={shot.shot_id}
                    className="flex flex-col items-center bg-gray-800 px-3 py-2 rounded-lg shadow-md"
                    style={{ minWidth: "100px" }}
                  >
                    {/* Shot Number */}
                    <span className="text-gray-200 font-mono text-sm mb-1">
                      {shot.shot_number}
                    </span>

                    {/* Dropdown */}
                    <select
                      className="bg-gray-700 text-white text-sm px-2 py-1 rounded-md w-full"
                      value={shot.status}
                      onChange={(e) =>
                        updateStoryboardStatus(
                          shot.shot_id,
                          shot.step_id,       // <-- universal SB step_id
                          e.target.value
                        )
                      }
                    >
                      {storyboardOptions.map((opt) => (
                        <option
                          key={opt.node_id}
                          value={opt.status}
                          style={{
                            backgroundColor: opt.color,
                            color: "black",
                            fontWeight: "bold",
                          }}
                        >
                          {opt.status}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}

              </div>
            )}
          </div>
        )}



        {selectedFile ? (
          <VideoPlayer
            isDrawing={isDrawing}
            brushColor={brushColor}
            brushSize={brushSize}
            frameAnnotations={frameAnnotations}
            setFrameAnnotations={setFrameAnnotations}
            currentFrame={currentFrame}
            setCurrentFrame={setCurrentFrame}
            clearCanvas={clearCurrentFrame}
            undoStack={undoStack}
            setUndoStack={setUndoStack}
            redoStack={redoStack}
            setRedoStack={setRedoStack}
            selectedFile={selectedFile}
            undoLastChange={undoLastChange}
            redoLastChange={redoLastChange}
            setRedrawCanvas={handleSetRedrawCanvas}
            setClearCanvas={handleSetClearCanvas}
            canvasKey={canvasKey}
            onionSkinConfig={onionSkinConfig}
            compareAnnotations={compareAnnotations}
            compareEnabled={compareConfig.enabled}
            compareColor={compareConfig.color}
          />
        ) : (
          <div className="flex items-center justify-center h-full text-gray-400">
            🎬 Select a video or image
          </div>
        )}

      </div>

      <div
        className="w-[270px] flex-shrink-0 overflow-y-auto bg-gray-900 p-2 border-l border-gray-700"
        style={{
          maxWidth: "270px",
          minWidth: "270px",
          boxSizing: "border-box",
        }}
      >
        {/* 🎬 Start Review Session Button */}
        <div className="w-full mb-1 flex justify-left">
          <button
            id="openSceneModalBtn"
            onClick={() => setShowSceneModal(true)} // 👈 opens modal
            className="bg-blue-600 hover:bg-blue-500 text-white text-sm px-2 py-1 rounded-md"
          >
            🎬 Start Review Session
          </button>
          {/* Hidden playback trigger for auto-start */}
          <button
            id="autoStartReviewBtn"
            style={{ display: "none" }}
            onClick={() => {
              console.log("🎬 Auto-starting Scene Review playback...");
              const playBtn =
                typeof document !== "undefined"
                  ? document.getElementById("scenePlayBtn")
                  : null;
              if (playBtn) playBtn.click();
            }}
          >
            Hidden Auto-Start
          </button>
        </div>

        {/* 🎞️ Open Review Clips Button */}
        <div className="w-full mb-4 flex justify-left">
          <button
            onClick={() => {
              if (typeof window !== "undefined") {
                window.open("/review/scene_reviews", "_blank");
              }
            }}
            className="bg-purple-700 hover:bg-purple-600 text-white text-sm px-2 py-1 rounded-md mt-2"
          >
            🎞️ Open Review Clips
          </button>
        </div>
        <div>
        <button onClick={handleOpenPrevious}>
          View Previous Version
        </button>
        </div>

        <DrawingTools
          brushColor={brushColor}
          setBrushColor={setBrushColor}
          brushSize={brushSize}
          setBrushSize={setBrushSize}
          isDrawing={isDrawing}
          setIsDrawing={setIsDrawing}
          clearCanvas={clearCurrentFrame}
          undoLastChange={undoLastChange}
          redoLastChange={redoLastChange}
          clearAll={handleClearAll}
        />

        <OnionSkinSettings
          config={onionSkinConfig}
          setConfig={setOnionSkinConfig}
        />

        <CompareVersionSettings
          versions={compareVersions}
          selectedVersion={compareVersion}
          onSelectVersion={handleSelectCompareVersion}
          config={compareConfig}
          setConfig={setCompareConfig}
        />

        <div className="bg-gray-800 p-3 rounded-lg mt-4">
          <h3 className="text-sm font-medium mb-2">📝 Frame Note:</h3>
          <textarea
            className="w-full h-16 p-2 rounded-md bg-gray-700 text-white"
            value={noteInput}
            onChange={(e) => setNoteInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.code === "Space") {
                e.stopPropagation();
                e.preventDefault();   // ✅ stops page scroll + lets global handler fire
              }

              if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                setFrameAnnotations((prev) => ({
                  ...prev,
                  [currentFrame]: {
                    ...(prev[currentFrame] || {}),
                    note: noteInput,
                    strokes: prev[currentFrame]?.strokes || [],
                  },
                }));
                Swal.fire({
                  toast: true,
                  icon: "success",
                  title: "Note saved!",
                  position: "bottom-end",
                  showConfirmButton: false,
                  timer: 1200,
                  timerProgressBar: true,
                });
              }
            }}
            placeholder="Type a note for this frame..."
          />

          <button
            onClick={() => {
              setFrameAnnotations((prev) => ({
                ...prev,
                [currentFrame]: {
                  ...(prev[currentFrame] || {}),
                  note: noteInput,
                  strokes: prev[currentFrame]?.strokes || [],
                },
              }));
              Swal.fire({
                toast: true,
                icon: "success",
                title: "Note saved!",
                position: "bottom-end",
                showConfirmButton: false,
                timer: 1200,
                timerProgressBar: true,
              });
            }}
            className="mt-2 bg-green-600 hover:bg-green-700 text-white text-sm px-3 py-1 rounded"
          >
            💾 Save Note
          </button>
        </div>
        <div className="bg-gray-800 p-3 rounded-lg mt-4">

          {/* Start / Stop Recording + Export Buttons */}
          <div className="flex flex-wrap justify-left gap-2">
          <button
            id="startObsBtn"
            onClick={() => {
              if (!selectedAssignment) {
                alert("No assignment selected!");
                return;
              }

              // --- STEP (PL/BL/BP/P) RESOLVE ---
              const STEP_MAP = {
                Planning: "PL",
                Blocking: "BL",
                "Blocking Plus": "BP",
                Polish: "P",
              };

              const rawLabel = (
                selectedAssignment?.step_name ??
                selectedAssignment?.step ??
                selectedAssignment?.phase ??
                ""
              )
                .toString()
                .trim();

              // 1️⃣ map from human label
              let step = STEP_MAP[rawLabel] || "";

              // 2️⃣ fallback: assignment name suffix like "Jump_BP" or "Jump BP"
              if (!step) {
                const an = ((selectedAssignment?.assignment_name ?? "") + "").replaceAll(" ", "_");
                const m1 = an.match(/_(PL|BL|BP|P)\b/i);
                if (m1) step = m1[1].toUpperCase();
              }

              // 3️⃣ fallback: filename contains _PL/_BL/_BP/_P_
              if (!step) {
                const fname = ((selectedAssignment?.file_name ?? selectedAssignment?.file ?? "") + "")
                  .split(/[\\/]/)
                  .pop();
                const m2 = fname.match(/_(PL|BL|BP|P)_/i);
                if (m2) step = m2[1].toUpperCase();
              }

              console.log("🔎 resolved step:", step);

              // ---- payload (now includes step) ----
              const payload = {
                assignment: selectedAssignment?.assignment_name || "UnknownAssignment",
                student: selectedAssignment?.student_name || "UnknownStudent",
                ...(step ? { step } : {}),
              };

              console.log("📤 Sending OBS Start payload:", payload);

              fetch("http://172.20.1.66:5001/obs/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
              })
                .then((res) => res.json())
                .then((data) => {
                  console.log("✅ OBS Start Response:", data);
                })
                .catch((err) => {
                  console.error("❌ OBS Start Error:", err);
                });
            }}
            className="px-2 py-1 bg-green-600 hover:bg-green-700 text-sm text-white rounded-md"
          >
            🎬 Start OBS Recording
          </button>

          <button
            id="stopObsBtn"
            onClick={() => {
              fetch("http://172.20.1.66:5001/obs/stop", {
                method: "POST",
              })
                .then((res) => res.json())
                .then((data) => {
                  console.log("🛑 OBS Stop Response:", data);
                })
                .catch((err) => {
                  console.error("❌ OBS Stop Error:", err);
                });
            }}
            className="px-2 py-1 bg-red-600 hover:bg-red-700 text-white text-sm rounded-md"
          >
            🛑 Stop OBS Recording
          </button>

            <button
              onClick={async () => {
                console.log("🔥 Export button clicked");
                // Fetch current semester classes
                let classesPayload;
                try {
                  const res = await fetch(`${API_BASE_URL}/review/current_semester_classes`);
                  classesPayload = await res.json();
                  console.log("🔥 classesPayload:", classesPayload);
                } catch (err) {
                  console.error("❌ Failed to load classes:", err);
                  Swal.fire("Error", "Could not load classes.", "error");
                  return;
                }

                const classes = Array.isArray(classesPayload?.classes) ? classesPayload.classes : [];
                const semesterLabel = classesPayload?.semester || null;

                if (classes.length === 0) {
                  Swal.fire("No Classes Found", "No classes were found for the current semester.", "warning");
                  return;
                }

                const inputOptions = {
                  ALL: "📦 Export All Classes",
                };

                for (const c of classes) inputOptions[c] = c;

                const { value: className } = await Swal.fire({
                  title: semesterLabel ? `Export Grades (${semesterLabel})` : "Export Grades",
                  input: "select",
                  inputOptions,
                  inputPlaceholder: "Select a class",
                  showCancelButton: true,
                });

                if (!className) return;

                let url = "";
                let filename = "";

                if (className === "ALL") {
                  url = `${API_BASE_URL}/review/export_all_grades_zip`;
                  filename = "all_classes.zip";
                } else {
                  url = `${API_BASE_URL}/review/export_canvas_csv?class=${encodeURIComponent(className)}`;
                  filename = `${className}.csv`;
                }

                fetch(url)
                  .then((res) => res.blob())
                  .then((blob) => {
                    const downloadUrl = window.URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = downloadUrl;
                    a.download = filename;
                    a.click();
                  })
                  .catch((err) => {
                    console.error("❌ Failed to download:", err);
                    Swal.fire("Error", "Could not download export.", "error");
                  });
              }}

            className="px-2 py-1 bg-purple-600 hover:bg-purple-700 text-white text-sm rounded-md"
          >
            📥 Export Grades FOOL
          </button>
          </div>




        </div>
        <div className="bg-gray-800 p-3 rounded-lg mt-4">
        <button id="openPreferences" class="toolbar-btn">
          ⚙️ Preferences
        </button>
        </div>
      </div>
    </div>
    </div>
  );
  


}