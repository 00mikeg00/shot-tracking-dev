"use client";
import React from "react";
import { useRef, useState, useEffect } from "react";
import DrawingCanvas from "./DrawingCanvas";
import VideoTimeline from "./VideoTimeline";

export default function VideoPlayer({
    isDrawing,
    brushColor,
    brushSize,
    frameAnnotations,
    setFrameAnnotations,
    frameNotes,
    currentFrame,
    setCurrentFrame,
    setClearCanvas,
    canvasKey,
    setRedrawCanvas,
    undoStack,
    setUndoStack,
    redoStack,
    setRedoStack,
    selectedFile,
    undoLastChange,
    redoLastChange,
    onionSkinConfig,
    selectedAssignment,
    onSeek,
    onDraw
}) {
    const [videoSrc, setVideoSrc] = useState(null);
    const [isPlaying, setIsPlaying] = useState(false);
    const isPlayingRef = useRef(isPlaying);
    const [volume, setVolume] = useState(1);
    const [playbackRate, setPlaybackRate] = useState(1);
    const [isLooping, setIsLooping] = useState(false);
    const [totalFrames, setTotalFrames] = useState(1);
    const [onionSkinEnabled, setOnionSkinEnabled] = useState(false);

    const videoRef = useRef(null);
    const isDraggingRef = useRef(false);
    const fps = 24;

    useEffect(() => {
        if (!selectedFile) {
            setVideoSrc(null);   // ✅ clear the video when deselected
            return;
        }
        console.log("VideoPlayer received new file:", selectedFile);
        setVideoSrc(selectedFile);
    }, [selectedFile]);

    useEffect(() => {
        if (videoRef.current) {
            videoRef.current.volume = volume;
            videoRef.current.muted = volume === 0;
        }
    }, [volume, videoSrc]);

    useEffect(() => {
        isPlayingRef.current = isPlaying;
    }, [isPlaying]);

    // Toggle Play/Pause
    const togglePlay = () => {
        if (!videoRef.current) return;

        if (isPlayingRef.current) {
            // currently playing → pause
            videoRef.current.pause();
            setIsPlaying(false);
        } else {
            // currently paused → reset if at end
            if (videoRef.current.currentTime >= videoRef.current.duration) {
                videoRef.current.currentTime = 1;
                setCurrentFrame(0);
            }
            const playPromise = videoRef.current.play();
            if (playPromise !== undefined) {
                playPromise.catch(err => console.warn("Playback error:", err));
            }
            setIsPlaying(true);
        }
    };



    // Navigate to nearest mark
    const jumpToNearestMark = (direction) => {
        if (!videoRef.current || Object.keys(frameAnnotations).length === 0) return;
        const frameNumbers = Object.keys(frameAnnotations).map(Number).sort((a, b) => a - b);
        if (frameNumbers.length === 0) return;

        let newFrame = currentFrame;
        if (direction === "prev") {
            for (let i = frameNumbers.length - 1; i >= 0; i--) {
                if (frameNumbers[i] < currentFrame) {
                    newFrame = frameNumbers[i];
                    break;
                }
            }
        } else if (direction === "next") {
            for (let i = 0; i < frameNumbers.length; i++) {
                if (frameNumbers[i] > currentFrame) {
                    newFrame = frameNumbers[i];
                    break;
                }
            }
        }
        if (newFrame !== currentFrame) {
            videoRef.current.currentTime = newFrame / fps;
            setCurrentFrame(newFrame);
        }
    };

    // useEffect(() => {
    //     if (!isPlaying) return;

    //     const step = () => {
    //         if (!videoRef.current) return;
    //         const current = videoRef.current.currentTime;
    //         const next = current + 1 / fps;

    //         videoRef.current.currentTime = next;
    //         setCurrentFrame(Math.floor(next * fps));
    //     };

    //     const interval = setInterval(step, 1000 / fps);
    //     return () => clearInterval(interval);
    // }, [isPlaying, fps, isLooping]);

    

    // Handle Volume Change
    const changeVolume = (event) => {
        const newVolume = parseFloat(event.target.value);
        if (videoRef.current) {
            videoRef.current.volume = newVolume;
        }
        setVolume(newVolume);
    };

    // Toggle Looping
    const toggleLoop = () => {
        setIsLooping((prev) => !prev);
        if (videoRef.current) {
            videoRef.current.loop = !isLooping;
        }
    };

      

    // Update Total Frames When Video Loads
    useEffect(() => {
        const updateTotalFrames = () => {
            if (videoRef.current) {
                const duration = videoRef.current.duration;
                setTotalFrames(Math.floor(duration * fps) || 1);

                // ✅ force start at frame 1
                videoRef.current.currentTime = 1 / fps;
                setCurrentFrame(0);
            }
        };


        const video = videoRef.current;
        if (video) {
            video.addEventListener("loadedmetadata", updateTotalFrames);
        }

        return () => {
            if (video) {
                video.removeEventListener("loadedmetadata", updateTotalFrames);
            }
        };
    }, [videoSrc]);


    // ✅ Reset when video ends
    useEffect(() => {
        const video = videoRef.current;
        if (!video) return;

        const handleEnded = () => {
            video.pause();
            setIsPlaying(false);
            video.currentTime = 0;   // reset video
            setCurrentFrame(0);      // reset scrubber
        };

        video.addEventListener("ended", handleEnded);
        return () => video.removeEventListener("ended", handleEnded);
    }, [videoSrc]);


    // Update Current Frame on Video Play
    useEffect(() => {
        const updateFrame = () => {
            const video = videoRef.current;
            if (!video || isDraggingRef.current || video.paused) return;

            const duration = video.duration;
            const current = video.currentTime;
            const frame = Math.floor(current * fps);

            console.log("🎞 Frame check:", frame, current.toFixed(3)); 
            setCurrentFrame(frame);

            if (current >= duration || frame >= Math.floor(duration * fps)) {
                video.pause();
                setIsPlaying(false);
                video.currentTime = 0;       // ✅ reset to beginning
                setCurrentFrame(0);
            }

        };

        const video = videoRef.current;
        if (video) {
            video.addEventListener("timeupdate", updateFrame);
        }

        return () => {
            if (video) {
                video.removeEventListener("timeupdate", updateFrame);
            }
        };
    }, [videoSrc]);




    // Handle Keyboard Shortcuts, Exclude Left Panel
    useEffect(() => {
        const handleKeyDown = (event) => {
            const leftPanel = document.getElementById("left-panel");
            if (leftPanel?.contains(event.target)) return;

            switch (event.code) {
                case "Space":
                case " ":
                    if (
                        event.target.tagName === "TEXTAREA" ||
                        event.target.tagName === "INPUT" ||
                        event.target.tagName === "SELECT"
                    ) {
                        return; // ✅ ignore typing in fields & dropdowns
                    }
                    event.preventDefault();
                    console.log("⏯️ Spacebar pressed, isPlaying =", isPlayingRef.current);
                    togglePlay();
                    break;



                case "Comma": // ⏪ ALT + , = Previous Frame
                    if (event.altKey) {
                        event.preventDefault();
                        if (videoRef.current) {
                            const newFrame = Math.max(0, currentFrame - 1);
                            videoRef.current.currentTime = newFrame / fps;
                            setCurrentFrame(newFrame);
                        }
                    } else {
                        event.preventDefault();
                        jumpToNearestMark("prev");
                    }
                    break;

                case "Period": // ⏩ ALT + . = Next Frame
                    if (event.altKey) {
                        event.preventDefault();
                        if (videoRef.current) {
                            const lastFrame = Math.floor(videoRef.current.duration * fps);
                            const newFrame = Math.min(lastFrame, currentFrame + 1);
                            videoRef.current.currentTime = newFrame / fps;
                            setCurrentFrame(newFrame);
                            console.log("⏩ Manual step forward → Frame:", newFrame);
                        }
                    }
                 else {
                        event.preventDefault();
                        jumpToNearestMark("next");
                    }
                    break;

                default:
                    break;
            }

        };

        window.addEventListener("keydown", handleKeyDown, { capture: true });
        return () => window.removeEventListener("keydown", handleKeyDown, { capture: true });
    }, [currentFrame, frameAnnotations]);


    return (
        <div className="flex flex-col items-center w-full">
            {/* Main Video Area */}
            <div className="flex justify-center items-center w-full max-w-[1600px]"
                style={{ maxHeight: "calc(100vh - 220px)" }}>
                <div className="relative w-full h-full mx-auto border-2 border-gray-500 bg-black">
                    {selectedFile ? (
                        /\.(png|jpe?g)$/i.test(selectedFile) ? (
                            <>
                                <img
                                    ref={videoRef} // ✅ same ref as video for drawing
                                    src={selectedFile}
                                    className="w-full h-auto max-h-[calc(100vh-260px)] object-contain"
                                    alt="Uploaded image"
                                    // Video's canvas-resize listener fires off "resize"/"layoutchange"
                                    // (see SideBar.jsx's collapse toggle for the same pattern) --
                                    // images have no equivalent to <video>'s loadedmetadata, so without
                                    // this the drawing canvas stays at its default 300x150 size until
                                    // something else happens to trigger a resize.
                                    onLoad={() => window.dispatchEvent(new Event("resize"))}
                                />
                                {videoRef.current && (
                                    <DrawingCanvas
                                        key={canvasKey}     
                                        videoElement={videoRef.current}
                                        currentFrame={currentFrame}
                                        frameAnnotations={frameAnnotations}
                                        setFrameAnnotations={setFrameAnnotations}
                                        isDrawingMode={isDrawing}
                                        brushColor={brushColor}
                                        brushSize={brushSize}
                                        setClearCanvas={setClearCanvas}
                                        setRedrawCanvas={setRedrawCanvas} 
                                        undoStack={undoStack}
                                        setUndoStack={setUndoStack}
                                        redoStack={redoStack}
                                        setRedoStack={setRedoStack}
                                        undoLastChange={undoLastChange}
                                        redoLastChange={redoLastChange}
                                        onionSkinEnabled={onionSkinEnabled}
                                        onionSkinConfig={onionSkinConfig}
                                    />
                                )}
                            </>
                        ) : (
                            <>
                                    {selectedFile.match(/\.(webm|mp4|mov)$/i) ? (
                                        <video
                                            ref={videoRef}
                                            src={selectedFile}
                                            className="w-full h-auto max-h-[calc(100vh-260px)] object-contain"
                                            controls={false}
                                        />
                                    ) : (
                                        <div className="text-red-500">Unsupported file format</div>
                                    )}

                                    {videoRef.current && (
                                        <DrawingCanvas
                                            key={canvasKey}     
                                            videoElement={videoRef.current}
                                            currentFrame={currentFrame}
                                            frameAnnotations={frameAnnotations}
                                            setFrameAnnotations={setFrameAnnotations}
                                            isDrawingMode={isDrawing}
                                            brushColor={brushColor}
                                            brushSize={brushSize}
                                            setClearCanvas={setClearCanvas}
                                            setRedrawCanvas={setRedrawCanvas} 
                                            undoStack={undoStack}
                                            setUndoStack={setUndoStack}
                                            redoStack={redoStack}
                                            setRedoStack={setRedoStack}
                                            undoLastChange={undoLastChange}
                                            redoLastChange={redoLastChange}
                                            onionSkinEnabled={onionSkinEnabled}
                                            onionSkinConfig={onionSkinConfig}
                                        />
                                    )}
                            </>
                        )
                    ) : (
                        <p className="text-gray-400 text-center">🎬 Select a video or image</p>
                    )}

                </div>
            </div>
            {/* Timeline Below Video */}
            {(selectedAssignment || selectedFile) && (
                <div className="w-full max-w-[1600px] mt-2 px-4">
                    <VideoTimeline
                        key={Object.keys(frameAnnotations).filter(k => k !== "__refresh").join(",")}
                        videoRef={videoRef}
                        currentFrame={currentFrame}
                        setCurrentFrame={setCurrentFrame}
                        totalFrames={totalFrames}
                        frameAnnotations={frameAnnotations}
                        fps={fps}
                    />
                </div>
            )}
            {/* Video Controls */}
            {selectedFile && !/\.(png|jpe?g)$/i.test(selectedFile) && (
                <div className="mt-1 flex items-center justify-center space-x-4 bg-gray-800 text-white p-2 rounded-lg">
                    {/* Play Button (Fixed Width) */}
                    <button
                        onClick={togglePlay}
                        className="px-4 py-2 bg-blue-500 text-white w-[9ch] rounded-lg hover:bg-blue-600 transition"
                    >
                        {isPlaying ? "Pause" : "Play"}
                    </button>

                    {/* Loop Button */}
                    <button
                        onClick={toggleLoop}
                        className={`px-3 py-1 rounded ${isLooping ? "bg-green-500" : "bg-gray-700 hover:bg-gray-600"}`}
                    >
                        🔁
                    </button>

                    {/* Volume Button & Slider */}
                    <div className="flex items-center space-x-2">
                        <button
                            onClick={() => {
                                const newVolume = volume > 0 ? 0 : 1;
                                setVolume(newVolume);
                                if (videoRef.current) {
                                    videoRef.current.volume = newVolume;
                                    videoRef.current.muted = newVolume === 0;
                                }
                            }}
                            className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded"
                        >
                            {volume > 0 ? "🔊" : "🔇"}
                        </button>
                        <input
                            type="range"
                            min="0"
                            max="1"
                            step="0.1"
                            value={volume}
                            onChange={changeVolume}
                            className="cursor-pointer"
                        />
                    </div>

                    {/* Current Frame Display (Fixed Width) */}
                    <div className="px-3 py-1 bg-gray-700 rounded w-[5ch] text-center">
                        {String(currentFrame + 1).padStart(3, "0")}
                    </div>
                </div>

            )}
            </div>
    );

}