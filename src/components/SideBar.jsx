import React, { useState, useEffect, useRef } from "react";

export default function SideBar({
    fileList,
    selectedCategory,
    setSelectedCategory,
    handleFileClick,
    setSelectedAssignment,
    apiBaseUrl,
    classPerm,
    filmPerm
}) {
    const [searchTerm, setSearchTerm] = useState("");
    const [isAssignmentsOpen, setIsAssignmentsOpen] = useState(true);
    const [isClassesOpen, setIsClassesOpen] = useState(true);
    const [isFilmsOpen, setIsFilmsOpen] = useState(true);
    const [collapsed, setCollapsed] = useState(false);

    // Realign canvas when the sidebar collapses/expands
    useEffect(() => {
        // Some CSS layout changes don't fire a real window resize.
        window.dispatchEvent(new Event('resize'));      // triggers DrawingCanvas listener
        window.dispatchEvent(new Event('layoutchange')); // optional custom hook for robustness
    }, [collapsed]);


    // ✅ Sidebar folder state
    const [openClasses, setOpenClasses] = useState({});


    // ✅ Load saved state on mount
    useEffect(() => {
        const savedState = localStorage.getItem("openClasses");
        if (savedState) {
            try {
                setOpenClasses(JSON.parse(savedState));
            } catch (e) {
                console.warn("Failed to parse saved openClasses", e);
            }
        }
    }, []);

    // ✅ Save state whenever it changes
    useEffect(() => {
        localStorage.setItem("openClasses", JSON.stringify(openClasses));
    }, [openClasses]);

    // ✅ Toggle function stays the same
    const toggleClass = (key) => {
        setOpenClasses((prev) => ({
            ...prev,
            [key]: !prev[key],
        }));
    };

    // 🔑 Add keyboard shortcut: Ctrl+B to toggle sidebar
    useEffect(() => {
        function handleKeyDown(e) {
            // Example: Ctrl + B
            if (e.ctrlKey && e.key.toLowerCase() === "b") {
                e.preventDefault();
                setCollapsed(prev => !prev);
            }
        }

        window.addEventListener("keydown", handleKeyDown);
        return () => window.removeEventListener("keydown", handleKeyDown);
    }, []);



    const STEP_LABELS = {
        THUMB: "Thumbnails",
        SB: "Storyboards",
        LAY: "FB Layout",
        ANIM: "FB Animation",
        LIGHT: "FB Lighting"
        // Expand as needed
    };
      

    // Utility to organize reviewed films
    // ✅ Fixed version
    function organizeReviewedFilms(films_reviewed) {
        const result = {};

        for (const file of films_reviewed) {
            if (!file || typeof file !== "object" || !file.file_name) continue;

            const filmTitle = extractFilmName(file.file_name);
            const filePath = file.file_path || "";
            const stepMatch = file.file_name.match(/_([A-Z]+)_/i);
            const stepCode = stepMatch ? stepMatch[1].toUpperCase() : null;
            const stepLabel = STEP_LABELS[stepCode] || null;


            if (!result[filmTitle]) {
                result[filmTitle] = {
                    Scenes: {
                        Thumbnails: [],
                        Storyboards: []
                    },
                    Shots: [],
                    Assets: {
                        Sets: [],
                        BGs: [],
                        "Props 2D": [],
                        "Props 3D": []
                    },
                    StepBuckets: {}  // ✅ NEW: dynamic section
                };
            }
            

            if (stepLabel) {
                if (!result[filmTitle].StepBuckets[stepLabel]) {
                    result[filmTitle].StepBuckets[stepLabel] = [];
                }
                result[filmTitle].StepBuckets[stepLabel].push(file);
            } else if (filePath.includes("/assets/")) {
                if (filePath.includes("sets")) {
                    result[filmTitle].Assets.Sets.push(file);
                } else if (filePath.includes("bgs")) {
                    result[filmTitle].Assets.BGs.push(file);
                } else if (filePath.includes("props_2d")) {
                    result[filmTitle].Assets["Props 2D"].push(file);
                } else if (filePath.includes("props_3d")) {
                    result[filmTitle].Assets["Props 3D"].push(file);
                }
            }
            
        }
        return result;
    }
    

    function extractFilmName(filename) {
        // e.g., "Dawn of the Dead_020_THUMB_v1_R.mov" → "Dawn of the Dead"
        const match = typeof filename === "string" ? filename.match(/^(.*?)(?=_\d+)/) : null;
        return match ? match[1].replace(/[_-]/g, ' ').trim() : "Unknown Film";
    }


    // Filter files based on the search term
    const filterFiles = (files) => {
        return files.filter(file =>
            file?.file_name &&
            !file.file_name.toLowerCase().endsWith(".json") &&
            (
                file.file_name.endsWith(".webm") ||
                file.file_name.endsWith(".mov") ||
                file.file_name.endsWith(".mp4") ||
                // Planning drawings (still images) — additive to the video
                // extensions above, not a replacement.
                file.is_planning_drawing ||
                /\.(png|jpe?g)$/i.test(file.file_name) ||
                // Video references — uploads are already .webm (covered
                // above); links use a synthetic .url name.
                file.is_video_reference
            )
        );
    };

    // 🔍 Helper: also apply the search filter if searchTerm has text
    const applySearchFilter = (files) => {
        if (!searchTerm) return files;
        const term = searchTerm.toLowerCase();
        return files.filter(file => file.file_name?.toLowerCase().includes(term));
    };


    return (
        <div className="flex">
                    {/* Sidebar wrapper */}
                    <div
                className={`bg-gray-900 h-full overflow-y-auto max-h-screen transition-all duration-300 ${collapsed ? "w-0 p-0 overflow-hidden" : "w-[480px] p-4"
                            }`}
                    >
                        {!collapsed && (
                            <>
                                {/* 🔎 Search Bar */}
                                <input
                                    type="text"
                                    placeholder="Search files..."
                                    value={searchTerm}
                                    onChange={(e) => setSearchTerm(e.target.value)}
                                    className="bg-grey-500 text-white p-2 w-full"
                                />
                            </>
                        )}


            {/* Assignments to Review - Collapsible */}
            {classPerm >= 2 && (
                <>
                <div
                onClick={() => setIsAssignmentsOpen(!isAssignmentsOpen)}
                className="cursor-pointer font-bold flex items-center"
                >
                📂 Assignments to Review ({filterFiles(fileList?.assignments || []).length})
                </div>
                {isAssignmentsOpen && (
                <div className="ml-4">
                    {Object.entries(
                    (fileList?.assignments || []).reduce((acc, file) => {
                        const className = file.class_name || "Unassigned Class";
                        if (!acc[className]) acc[className] = [];
                        acc[className].push(file);
                        return acc;
                    }, {})
                    ).map(([className, files]) => {
                    const uniqueKey = `assignments::${className}`;
                    const isOpen = openClasses[uniqueKey];

                    return (
                        <div key={uniqueKey} className="mt-2">
                        {/* Clickable class header */}
                        <div
                            className="cursor-pointer font-semibold text-blue-300"
                            onClick={() => toggleClass(uniqueKey)}
                        >
                            {isOpen ? "📂" : "📁"} {className}
                        </div>

                        {/* Only show files if open */}
                            {isOpen && (
                                <div className="ml-4">
                                    {Object.entries(
                                        files.reduce((acc, file) => {
                                            const baseName = file.file_name.replace(/\.[^/.]+$/, "");
                                            const displayName = baseName.split("_")[0].trim(); // e.g. "Pose #4"

                                            // sanitize for React keys
                                            const safeKey = displayName.replace(/[^a-zA-Z0-9 ]/g, "_");

                                            if (!acc[safeKey]) acc[safeKey] = { displayName, files: [] };
                                            acc[safeKey].files.push(file);
                                            return acc;
                                        }, {})
                                    ).map(([safeKey, group]) => {
                                        const assignmentKey = `${uniqueKey}::${safeKey}`;
                                        return (
                                            <div key={assignmentKey} className="ml-2 mt-1">
                                                <div
                                                    className="cursor-pointer font-semibold text-yellow-300"
                                                    onClick={() => toggleClass(assignmentKey)}
                                                >
                                                    {openClasses[assignmentKey] ? "📂" : "📁"} {group.displayName}
                                                </div>

                                                {openClasses[assignmentKey] && (
                                                    <ul className="ml-4">
                                                        {group.files.map((file, idx) => (
                                                            <li
                                                                key={idx}
                                                                className="cursor-pointer hover:bg-gray-700 p-2 rounded-md text-sm"
                                                                onClick={() => {
                                                                    setSelectedAssignment?.(file);
                                                                    handleFileClick(file, "assignments");
                                                                }}
                                                            >
                                                                📄 {file.file_name}
                                                            </li>
                                                        ))}
                                                    </ul>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
    

                        </div>
                    );
                    })}
                </div>
                )}
                </>
            )}


            {/* 🎞 Films to Review */}
            {filmPerm >= 2 && (
                <>
                <div onClick={() => setIsFilmsOpen(!isFilmsOpen)} className="cursor-pointer font-bold flex items-center mt-4">
                    🎞 Films to Review ({filterFiles(Object.values(fileList?.films || {}).flat()).length})
                </div>
                {isFilmsOpen && (
                    <ul className="ml-4">
                        {filterFiles(Object.values(fileList?.films || {}).flat()).map((file, index) => (
                            <li key={index} className="cursor-pointer hover:bg-gray-700 px-2 py-1 rounded-md text-sm" onClick={() => {
                                handleFileClick(file, "films");
                                setSelectedCategory("films");
                            }}
                                onContextMenu={(e) => {
                                    e.preventDefault();
                                    import("sweetalert2").then(({ default: Swal }) => {
                                        Swal.fire({
                                            title: `Delete this file?`,
                                            text: file.file_name,
                                            icon: "warning",
                                            showCancelButton: true,
                                            confirmButtonColor: "#d33",
                                            cancelButtonColor: "#3085d6",
                                            confirmButtonText: "Yes, delete it!"
                                        }).then((result) => {
                                            if (result.isConfirmed) {
                                                fetch(`${apiBaseUrl}/review/delete_file?path=${encodeURIComponent(file.file_path)}`, {
                                                    method: "DELETE"
                                                })
                                                    .then(res => res.json())
                                                    .then(json => {
                                                        if (json.success) {
                                                            Swal.fire("Deleted!", "Your file has been deleted.", "success").then(() => {
                                                                window.location.reload();
                                                            });
                                                        } else {
                                                            Swal.fire("Error", json.error || "Delete failed", "error");
                                                        }
                                                    })
                                                    .catch(err => Swal.fire("Error", err.message || "Delete failed", "error"));
                                            }
                                        });
                                    });
                            }}
                            >
                                📄 {file.file_name}
                            </li>
                        ))}
                    </ul>
                )}
                </>
            )}


            {/* Classes (All Assignments) - Collapsible */}
            {classPerm >= 2 && (
                <>
                <div onClick={() => setIsClassesOpen(!isClassesOpen)} className="cursor-pointer font-bold flex items-center mt-4">
                    📂 Classes
                </div>
                {isClassesOpen && (
                    <>
                        {fileList?.all_assignments && Object.keys(fileList.all_assignments).length > 0 ? (
                            Object.entries(
                                Object.entries(fileList.all_assignments).reduce((acc, [classPath, files]) => {
                                    const [semester, ...classParts] = classPath.split(" - ");
                                    const className = classParts.join(" - ");
                                    if (!acc[semester]) acc[semester] = {};
                                    acc[semester][className] = files;
                                    return acc;
                                }, {})
                            ).map(([semester, classes]) => (
                                <div key={semester} className="mt-2">
                                    <h2 className="text-md font-bold text-green-300">{semester}</h2>
                                    {Object.entries(classes).map(([className, assignments]) => {
                                        const filteredFiles = applySearchFilter(filterFiles(assignments));
                                        if (filteredFiles.length === 0) return null;

                                        const uniqueKey = `${semester}::${className}`;

                                        return (
                                            <div key={uniqueKey} className="ml-4 mt-1">
                                                <div
                                                    className="cursor-pointer font-semibold text-blue-300"
                                                    onClick={() => toggleClass(uniqueKey)}
                                                >
                                                    {openClasses[uniqueKey] ? "📂" : "📁"} {className}
                                                </div>

                                                {openClasses[uniqueKey] && (
                                                    <div className="ml-4">
                                                        {Object.entries(
                                                            filteredFiles.reduce((acc, file) => {
                                                                const baseName = file.file_name.replace(/\.[^/.]+$/, ""); // strip extension
                                                                const firstUnderscore = baseName.indexOf("_");

                                                                // Assignment = everything before the first underscore
                                                                const assignmentName =
                                                                    firstUnderscore !== -1
                                                                        ? baseName.substring(0, firstUnderscore).trim()
                                                                        : baseName;

                                                                if (!acc[assignmentName]) acc[assignmentName] = [];
                                                                acc[assignmentName].push(file);
                                                                return acc;
                                                            }, {})
                                                        ).map(([assignmentName, files]) => {
                                                            const safeAssignmentKey = `${uniqueKey}::${assignmentName.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
                                                            return (
                                                                <div key={safeAssignmentKey} className="ml-2 mt-1">
                                                                    <div
                                                                        className="cursor-pointer font-semibold text-yellow-300"
                                                                        onClick={() => toggleClass(safeAssignmentKey)}
                                                                    >
                                                                        {openClasses[safeAssignmentKey] ? "📂" : "📁"} {assignmentName}
                                                                    </div>

                                                                    {openClasses[safeAssignmentKey] && (
                                                                        <ul className="ml-4">
                                                                            {files.map((file, idx) => (
                                                                                <li
                                                                                    key={idx}
                                                                                    className="cursor-pointer hover:bg-gray-700 px-2 py-1 rounded-md text-sm"
                                                                                    onClick={() => {
                                                                                        // Link-type video references aren't a servable
                                                                                        // local file -- there's nothing for the player
                                                                                        // to load, just open it where it lives.
                                                                                        if (file.is_video_reference && file.source_type === "link") {
                                                                                            window.open(file.external_url, "_blank", "noopener,noreferrer");
                                                                                            return;
                                                                                        }
                                                                                        setSelectedAssignment?.(file);
                                                                                        handleFileClick(file, "assignments");
                                                                                    }}
                                                                                    onContextMenu={(e) => {
                                                                                        e.preventDefault();
                                                                                        import("sweetalert2").then(({ default: Swal }) => {
                                                                                            Swal.fire({
                                                                                                title: `Delete this file?`,
                                                                                                text: file.file_name,
                                                                                                icon: "warning",
                                                                                                showCancelButton: true,
                                                                                                confirmButtonColor: "#d33",
                                                                                                cancelButtonColor: "#3085d6",
                                                                                                confirmButtonText: "Yes, delete it!",
                                                                                            }).then((result) => {
                                                                                                if (result.isConfirmed) {
                                                                                                    fetch(
                                                                                                        `${apiBaseUrl}/review/delete_file?path=${encodeURIComponent(file.file_path)}`,
                                                                                                        { method: "DELETE" }
                                                                                                    )
                                                                                                        .then((res) => res.json())
                                                                                                        .then((json) => {
                                                                                                            if (json.success) {
                                                                                                                Swal.fire(
                                                                                                                    "Deleted!",
                                                                                                                    "Your file has been deleted.",
                                                                                                                    "success"
                                                                                                                ).then(() => {
                                                                                                                    window.location.reload();
                                                                                                                });
                                                                                                            } else {
                                                                                                                Swal.fire(
                                                                                                                    "Error",
                                                                                                                    json.error || "Delete failed",
                                                                                                                    "error"
                                                                                                                );
                                                                                                            }
                                                                                                        })
                                                                                                        .catch((err) =>
                                                                                                            Swal.fire(
                                                                                                                "Error",
                                                                                                                err.message || "Delete failed",
                                                                                                                "error"
                                                                                                            )
                                                                                                        );
                                                                                                }
                                                                                            });
                                                                                        });
                                                                                    }}
                                                                                >
                                                                                    {file.is_video_reference
                                                                                        ? (file.source_type === "link" ? "🔗 Video reference (link)" : "🎥 " + file.file_name)
                                                                                        : <>📄 {file.file_name}</>}
                                                                                </li>
                                                                            ))}
                                                                        </ul>
                                                                    )}
                                                                </div>
                                                            );
                                                        })}
                                                    </div>
                                                )}


                                            </div>
                                        );
                                    })}
                                </div>
                            ))
                        ) : (
                            <p className="text-gray-400 ml-4">No assignments available</p>
                        )}

                    </>
                )}
                </>
            )} 

            {/* 🎬 Reviewed Films - Collapsible */}
            {filmPerm >= 2 && (
                <>
                <div onClick={() => setIsClassesOpen(!isClassesOpen)} className="cursor-pointer font-bold flex items-center mt-4">
                    🎬 Reviewed Films
                </div>

                {isClassesOpen && (
                    <>
                        {fileList?.films_reviewed && fileList.films_reviewed.length > 0 ? (
                            Object.entries(organizeReviewedFilms(fileList.films_reviewed)).map(([filmTitle, filmData]) => (
                                <div key={filmTitle} className="ml-4 mt-1">
                                    <div
                                        className="cursor-pointer font-semibold text-blue-300"
                                        onClick={() => toggleClass(filmTitle)}
                                    >
                                        {openClasses[filmTitle] ? "📂" : "📁"} {filmTitle}
                                    </div>

                                    {openClasses[filmTitle] && (
                                        <div className="ml-4">
                                            {/* Scenes */}
                                            {["Thumbnails", "Storyboards"].map((subtype) =>
                                                filmData.Scenes[subtype].length > 0 ? (
                                                    <div key={subtype} className="mt-1">
                                                        <div className="text-sm text-yellow-300">{subtype}</div>
                                                        <ul>
                                                            {filmData.Scenes[subtype]
                                                                .filter(file => !file.file_name.endsWith(".json"))
                                                                .map((file, idx) => (
                                                                    <li
                                                                        key={idx}
                                                                        className="cursor-pointer hover:bg-gray-700 p-2 rounded-md"
                                                                        onClick={() => {
                                                                            setSelectedCategory("films");
                                                                            handleFileClick(file, "films");
                                                                        }}
                                                                        onContextMenu={(e) => {
                                                                            e.preventDefault();
                                                                            import("sweetalert2").then(({ default: Swal }) => {
                                                                                Swal.fire({
                                                                                    title: `Delete this file?`,
                                                                                    text: file.file_name,
                                                                                    icon: "warning",
                                                                                    showCancelButton: true,
                                                                                    confirmButtonColor: "#d33",
                                                                                    cancelButtonColor: "#3085d6",
                                                                                    confirmButtonText: "Yes, delete it!"
                                                                                }).then((result) => {
                                                                                    if (result.isConfirmed) {
                                                                                        fetch(`${apiBaseUrl}/review/delete_file?path=${encodeURIComponent(file.file_path)}`, {
                                                                                            method: "DELETE"
                                                                                        })
                                                                                            .then(res => res.json())
                                                                                            .then(json => {
                                                                                                if (json.success) {
                                                                                                    Swal.fire("Deleted!", "Your file has been deleted.", "success").then(() => {
                                                                                                        window.location.reload();
                                                                                                    });
                                                                                                } else {
                                                                                                    Swal.fire("Error", json.error || "Delete failed", "error");
                                                                                                }
                                                                                            })
                                                                                            .catch(err => Swal.fire("Error", err.message || "Delete failed", "error"));
                                                                                    }
                                                                                });
                                                                            });
                                                                        }}
                                                                        
                                                                    >
                                                                        📄 {file.file_name}
                                                                    </li>
                                                                ))}
                                                        </ul>
                                                    </div>
                                                ) : null
                                            )}

                                            {/* Shots */}
                                            {filmData.Shots.length > 0 && (
                                                <div className="mt-1">
                                                    <div className="text-sm text-green-300">Shots</div>
                                                    <ul>
                                                        {filmData.Shots
                                                            .filter(file => !file.file_name.endsWith(".json"))
                                                            .map((file, idx) => (
                                                                <li
                                                                    key={idx}
                                                                    className="cursor-pointer hover:bg-gray-700 p-2 rounded-md"
                                                                    onClick={() => {
                                                                        setSelectedCategory("films");
                                                                        handleFileClick(file, "films");
                                                                    }}
                                                                    onContextMenu={(e) => {
                                                                        e.preventDefault();
                                                                        import("sweetalert2").then(({ default: Swal }) => {
                                                                            Swal.fire({
                                                                                title: `Delete this file?`,
                                                                                text: file.file_name,
                                                                                icon: "warning",
                                                                                showCancelButton: true,
                                                                                confirmButtonColor: "#d33",
                                                                                cancelButtonColor: "#3085d6",
                                                                                confirmButtonText: "Yes, delete it!"
                                                                            }).then((result) => {
                                                                                if (result.isConfirmed) {
                                                                                    fetch(`${apiBaseUrl}/review/delete_file?path=${encodeURIComponent(file.file_path)}`, {
                                                                                        method: "DELETE"
                                                                                    })
                                                                                        .then(res => res.json())
                                                                                        .then(json => {
                                                                                            if (json.success) {
                                                                                                Swal.fire("Deleted!", "Your file has been deleted.", "success").then(() => {
                                                                                                    window.location.reload();
                                                                                                });
                                                                                            } else {
                                                                                                Swal.fire("Error", json.error || "Delete failed", "error");
                                                                                            }
                                                                                        })
                                                                                        .catch(err => Swal.fire("Error", err.message || "Delete failed", "error"));
                                                                                }
                                                                            });
                                                                        });
                                                                    }}
                                                                    
                                                                >
                                                                    🎯 {file.file_name}
                                                                </li>
                                                            ))}
                                                    </ul>
                                                </div>
                                            )}

                                            {/* Assets */}
                                            {Object.entries(filmData.Assets).map(([assetType, files]) =>
                                                files.filter(file => !file.file_name.endsWith(".json")).length > 0 ? (
                                                    <div key={assetType} className="mt-1">
                                                        <div className="text-sm text-purple-300">{assetType}</div>
                                                        <ul>
                                                            {files
                                                                .filter(file => !file.file_name.endsWith(".json"))
                                                                .map((file, idx) => (
                                                                    <li
                                                                        key={idx}
                                                                        className="cursor-pointer hover:bg-gray-700 p-2 rounded-md"
                                                                        onClick={() => {
                                                                            setSelectedCategory("films");
                                                                            handleFileClick(file, "films");
                                                                        }}
                                                                        onContextMenu={(e) => {
                                                                            e.preventDefault();
                                                                            import("sweetalert2").then(({ default: Swal }) => {
                                                                                Swal.fire({
                                                                                    title: `Delete this file?`,
                                                                                    text: file.file_name,
                                                                                    icon: "warning",
                                                                                    showCancelButton: true,
                                                                                    confirmButtonColor: "#d33",
                                                                                    cancelButtonColor: "#3085d6",
                                                                                    confirmButtonText: "Yes, delete it!"
                                                                                }).then((result) => {
                                                                                    if (result.isConfirmed) {
                                                                                        fetch(`${apiBaseUrl}/review/delete_file?path=${encodeURIComponent(file.file_path)}`, {
                                                                                            method: "DELETE"
                                                                                        })
                                                                                            .then(res => res.json())
                                                                                            .then(json => {
                                                                                                if (json.success) {
                                                                                                    Swal.fire("Deleted!", "Your file has been deleted.", "success").then(() => {
                                                                                                        window.location.reload();
                                                                                                    });
                                                                                                } else {
                                                                                                    Swal.fire("Error", json.error || "Delete failed", "error");
                                                                                                }
                                                                                            })
                                                                                            .catch(err => Swal.fire("Error", err.message || "Delete failed", "error"));
                                                                                    }
                                                                                });
                                                                            });
                                                                        }}
                                                                        
                                                                    >
                                                                        🧱 {file.file_name}
                                                                    </li>
                                                                ))}
                                                        </ul>
                                                    </div>
                                                ) : null
                                            )}

                                            {/* 🔄 StepBuckets: dynamically mapped step groups like FB Layout, etc. */}
                                            {filmData.StepBuckets &&
                                                Object.entries(filmData.StepBuckets).map(([stepLabel, files]) =>
                                                    files.filter(file => !file.file_name.endsWith(".json")).length > 0 ? (
                                                        <div key={stepLabel} className="mt-1">
                                                            <div className="text-sm text-pink-300">{stepLabel}</div>
                                                            <ul>
                                                                {files
                                                                    .filter(file => !file.file_name.endsWith(".json"))
                                                                    .map((file, idx) => (
                                                                        <li
                                                                            key={idx}
                                                                            className="cursor-pointer hover:bg-gray-700 p-2 rounded-md"
                                                                            onClick={() => {
                                                                                setSelectedCategory("films");
                                                                                handleFileClick(file, "films");
                                                                            }}
                                                                            onContextMenu={(e) => {
                                                                                e.preventDefault();
                                                                                import("sweetalert2").then(({ default: Swal }) => {
                                                                                    Swal.fire({
                                                                                        title: `Delete this file?`,
                                                                                        text: file.file_name,
                                                                                        icon: "warning",
                                                                                        showCancelButton: true,
                                                                                        confirmButtonColor: "#d33",
                                                                                        cancelButtonColor: "#3085d6",
                                                                                        confirmButtonText: "Yes, delete it!"
                                                                                    }).then((result) => {
                                                                                        if (result.isConfirmed) {
                                                                                            fetch(`${apiBaseUrl}/review/delete_file?path=${encodeURIComponent(file.file_path)}`, {
                                                                                                method: "DELETE"
                                                                                            })
                                                                                                .then(res => res.json())
                                                                                                .then(json => {
                                                                                                    if (json.success) {
                                                                                                        Swal.fire("Deleted!", "Your file has been deleted.", "success").then(() => {
                                                                                                            window.location.reload();
                                                                                                        });
                                                                                                    } else {
                                                                                                        Swal.fire("Error", json.error || "Delete failed", "error");
                                                                                                    }
                                                                                                })
                                                                                                .catch(err => Swal.fire("Error", err.message || "Delete failed", "error"));
                                                                                        }
                                                                                    });
                                                                                });
                                                                            }}
                                                                            
                                                                        >
                                                                            🎞 {file.file_name}
                                                                        </li>
                                                                    ))}
                                                            </ul>
                                                        </div>
                                                    ) : null
                                                )}
                                        </div>
                                    )}
                                </div>
                            ))
                        ) : (
                            <p className="text-gray-400 ml-4">No reviewed films available</p>
                        )}
                    </>
                )}
                </>
            )}
            </div>
            {/* Toggle button always visible, sits next to sidebar */}
            <button
                onClick={() => setCollapsed(!collapsed)}
                className="bg-gray-700 text-white px-2 py-1 rounded m-2"
            >
                {collapsed ? "➡ Open" : "⬅ Collapse"}
            </button>

        </div>
    );
}