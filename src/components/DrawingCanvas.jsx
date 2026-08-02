"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";

export default function DrawingCanvas({
  videoElement,
  currentFrame,
  frameAnnotations,
  setFrameAnnotations,
  isDrawingMode,
  brushColor,
  brushSize,
  setClearCanvas,
  setRedrawCanvas,
  setUndoStack,
  setRedoStack,
  undoLastChange,
  redoLastChange,
  onionSkinConfig
}) {
  const canvasRef = useRef(null);
  const contextRef = useRef(null);
  const isDrawingRef = useRef(false);
  const currentStrokePointsRef = useRef([]);

  // videoElement is either a <video> (videoWidth/videoHeight) or an <img>
  // for planning drawings (naturalWidth/naturalHeight) — the two APIs
  // don't share property names, so every size read goes through these.
  const getMediaWidth = (el) => el?.videoWidth || el?.naturalWidth || 0;
  const getMediaHeight = (el) => el?.videoHeight || el?.naturalHeight || 0;

  const clearCanvas = (all = false) => {
    console.log("🧼 [DrawingCanvas.clearCanvas] all =", all, " currentFrame =", currentFrame,
      " hasEntry =", !!frameAnnotations[currentFrame],
      " strokesLen =", frameAnnotations[currentFrame]?.strokes?.length || 0,
      " hasNote =", !!frameAnnotations[currentFrame]?.note);

    if (!canvasRef.current) return;

    const ctx = canvasRef.current.getContext("2d");
    ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
    contextRef.current = ctx;

    if (all) {
      console.log("🧼 Full reset of all annotations");
      setFrameAnnotations({});
      setUndoStack([]);
      setRedoStack([]);
    } else {
      console.log("🧼 Clear current frame only");
      setFrameAnnotations((prev) => {
        const updated = structuredClone(prev);
        delete updated[currentFrame];
        return updated;
      });
      setUndoStack((prev) => prev.filter((item) => item.frame !== currentFrame));
      setRedoStack((prev) => prev.filter((item) => item.frame !== currentFrame));
    }
  };


  useEffect(() => {
    redrawCanvas();
  }, [frameAnnotations, currentFrame, onionSkinConfig]);




  const recomputeCanvasSize = useCallback(() => {
    if (!canvasRef.current || !videoElement) return;

    const canvas = canvasRef.current;
    const video = videoElement;

    if (getMediaWidth(video) === 0 || getMediaHeight(video) === 0) {
      requestAnimationFrame(() => setTimeout(recomputeCanvasSize, 50));
      return;
    }

    const rect = video.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;

    canvas.width = getMediaWidth(video) * dpr;
    canvas.height = getMediaHeight(video) * dpr;
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;

    const ctx = canvas.getContext("2d");
    ctx.resetTransform?.();
    ctx.scale(dpr, dpr);
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.strokeStyle = brushColor;
    ctx.lineWidth = brushSize;
    contextRef.current = ctx;

    console.log("📏 recomputeCanvasSize triggered");
    redrawCanvas?.();

  }, [videoElement, brushColor, brushSize]);


  // 3) REPLACE your existing useEffect({...}, [videoElement, brushColor, brushSize]) with this:
  useEffect(() => {
    const handleResize = () => {
      if (!canvasRef.current || !videoElement) return;
      const rect = videoElement.getBoundingClientRect();
      canvasRef.current.dataset.offsetLeft = rect.left;
      canvasRef.current.dataset.offsetTop = rect.top;
      recomputeCanvasSize();
    };

    // run once + watch window size + custom layoutchange event
    handleResize();
    window.addEventListener("resize", handleResize);
    window.addEventListener("layoutchange", handleResize);

    // optional: delayed recalc for sidebar animation
    const delayedRecalc = () => setTimeout(handleResize, 350);
    window.addEventListener("transitionend", delayedRecalc);

    return () => {
      window.removeEventListener("resize", handleResize);
      window.removeEventListener("layoutchange", handleResize);
      window.removeEventListener("transitionend", delayedRecalc);
    };
  }, [recomputeCanvasSize, videoElement]);


  

  // 🎨 Apply Brush Color & Size Dynamically
  useEffect(() => {
    if (contextRef.current) {
      contextRef.current.strokeStyle = brushColor;
      contextRef.current.lineWidth = brushSize;
    }
    redrawCanvas(); // ✅ force redraw so old strokes don’t disappear
  }, [brushColor, brushSize]);
  

  // Handle DPI Changes and Window Resizing
  useEffect(() => {
    const handleDPIChange = () => {
      console.log("📏 DPI changed, recalculating frame positions...");
      setClearCanvas?.();
      setRedrawCanvas?.();
    };

    window.matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`).addEventListener("change", handleDPIChange);

    return () => {
      window.matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`).removeEventListener("change", handleDPIChange);
    };
  }, [setClearCanvas, setRedrawCanvas]);

  // ✅ Redraw strokes on the canvas
  const redrawCanvas = () => {
    if (!canvasRef.current) return;
    const ctx = canvasRef.current.getContext("2d");
    ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);

    if (onionSkinConfig.enabled) {
      for (let i = 1; i <= onionSkinConfig.beforeCount; i++) {
        const frame = currentFrame - i;
        if (frameAnnotations[frame]) {
          drawFrameAnnotations(frameAnnotations[frame]?.strokes || [], onionSkinConfig.beforeColor, 0.3);
        }
      }
      for (let i = 1; i <= onionSkinConfig.afterCount; i++) {
        const frame = currentFrame + i;
        if (frameAnnotations[frame]) {
          drawFrameAnnotations(frameAnnotations[frame]?.strokes || [], onionSkinConfig.afterColor, 0.3);
        }
      }
    }

    const strokesForFrame = frameAnnotations[currentFrame]?.strokes || [];

    for (const stroke of strokesForFrame) {
      for (let i = 1; i < stroke.points.length; i++) {
        const prev = stroke.points[i - 1];
        const curr = stroke.points[i];

        ctx.lineWidth = stroke.size * (curr.pressure || 1);
        ctx.strokeStyle = stroke.color;
        ctx.beginPath();
        ctx.moveTo(prev.x, prev.y);
        ctx.lineTo(curr.x, curr.y);
        ctx.stroke();
      }
    }
  };

  //Pass functions up to `page.js`
  useEffect(() => {
    console.log("🔗 setClearCanvas registering:", typeof setClearCanvas);
    setClearCanvas?.(() => {
      return () => {
        console.log("🧼 clearCanvas() CALLED from parent");
        clearCanvas();
      };
    });
  }, [setClearCanvas]);

  useEffect(() => {
    setRedrawCanvas?.(() => redrawCanvas);
  }, [setRedrawCanvas]);

  


  //Hotkeys for Undo (CTRL+Z) & Redo (CTRL+Y)
  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.ctrlKey && event.key.toLowerCase() === "z") {
        event.preventDefault();
        console.log("🔄 CTRL+Z Pressed → Undo");
        undoLastChange();
        redrawCanvas(); // ✅ Ensure canvas updates after undo
      } else if (event.ctrlKey && event.key.toLowerCase() === "y") {
        event.preventDefault();
        console.log("🔄 CTRL+Y Pressed → Redo");
        redoLastChange();
        redrawCanvas(); // ✅ Ensure canvas updates after redo
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [undoLastChange, redoLastChange]);

  //Start Drawing
  const startDrawing = (e) => {
    if (!isDrawingMode || !contextRef.current) return;

    isDrawingRef.current = true;
    currentStrokePointsRef.current = [];

    const ctx = contextRef.current;
    ctx.beginPath();

    const { x, y } = getCursorPosition(e);
    const pressure = e.pressure > 0 ? e.pressure : 0.1; // Fallback for non-pressure input

    ctx.moveTo(x, y);
    currentStrokePointsRef.current.push({ x, y, pressure });
  };

  // Draw on Canvas
  // Draw on Canvas
  const draw = (e) => {
    if (!isDrawingRef.current || !contextRef.current) return;

    const ctx = contextRef.current;
    const { x, y } = getCursorPosition(e);
    const pressure = e.pressure > 0 ? e.pressure : 1;

    console.log("🖊 draw event:", {
      pointerType: e.pointerType,
      pressure: e.pressure,
      calcPressure: pressure,
      coords: { x, y }
    });

    const lastPoint = currentStrokePointsRef.current.at(-1) || { x, y, pressure };

    ctx.strokeStyle = brushColor;
    ctx.lineWidth = brushSize * pressure;
    ctx.beginPath();
    ctx.moveTo(lastPoint.x, lastPoint.y);
    ctx.lineTo(x, y);
    ctx.stroke();

    currentStrokePointsRef.current.push({ x, y, pressure });
  };


  // Stop Drawing
  const stopDrawing = () => {
    if (!isDrawingMode || !isDrawingRef.current) return;
    isDrawingRef.current = false;

    if (currentStrokePointsRef.current.length === 0) return;

    const stroke = {
      points: [...currentStrokePointsRef.current],
      color: brushColor,
      size: brushSize
    };

    setFrameAnnotations((prev) => {
      const updated = { ...prev };
      const frameData = updated[currentFrame];

      if (frameData && frameData.strokes) {
        updated[currentFrame] = {
          ...frameData,
          strokes: [...frameData.strokes, stroke],
        };
      } else {
        updated[currentFrame] = { strokes: [stroke] };
      }

      return updated;
    });
    

    setUndoStack((prev) => [...prev, { frame: currentFrame, stroke }]);
    setRedoStack([]);
    redrawCanvas();
    currentStrokePointsRef.current = [];
  };

  // Updated getCursorPosition with precise scaling correction
  const getCursorPosition = (e) => {
    const video = videoElement;
    if (!video) return { x: 0, y: 0 };

    const rect = video.getBoundingClientRect();

    // 🟩 Normalize mouse/pen position inside the video area (0–1 range)
    const normX = (e.clientX - rect.left) / rect.width;
    const normY = (e.clientY - rect.top) / rect.height;

    // 🟩 Convert normalized coords to actual media pixel space
    const x = normX * getMediaWidth(video);
    const y = normY * getMediaHeight(video);

    return { x, y };
  };



  function drawFrameAnnotations(annotations, overrideColor = null, opacity = 1.0) {
    const ctx = contextRef.current;
    ctx.save();
    ctx.globalAlpha = opacity;

    annotations.forEach((path) => {
      if (!path?.points?.length) return;

      ctx.strokeStyle = overrideColor || path.color;

      for (let i = 1; i < path.points.length; i++) {
        const prev = path.points[i - 1];
        const curr = path.points[i];

        ctx.lineWidth = path.size * (curr.pressure || 1); // ✅ Use pressure
        ctx.beginPath();
        ctx.moveTo(prev.x, prev.y);
        ctx.lineTo(curr.x, curr.y);
        ctx.stroke();
      }
    });

    ctx.restore();
  }

  return (
    <div className="absolute inset-0">
      <canvas
        ref={canvasRef}
        className={`w-full h-full ${isDrawingMode ? "cursor-crosshair" : "cursor-default"}`}
        style={{ touchAction: 'none' }}
        onPointerDown={startDrawing}
        onPointerMove={draw}
        onPointerUp={stopDrawing}
        onPointerLeave={stopDrawing}
      />
    </div>

  );
}