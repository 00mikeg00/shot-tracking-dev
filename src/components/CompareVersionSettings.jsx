"use client";

import React, { useState } from "react";

export default function CompareVersionSettings({ versions, selectedVersion, onSelectVersion, config, setConfig }) {
  const [isExpanded, setIsExpanded] = useState(false);

  const handleChange = (key, value) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <div className="bg-gray-900 text-white p-3 rounded shadow mb-4">
      {/* Collapsible Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex justify-between items-center bg-gray-800 px-3 py-2 rounded-md text-sm font-semibold"
      >
        <span>Compare to Version</span>
        <span>{isExpanded ? "▾" : "▸"}</span>
      </button>

      {/* Collapsible Content */}
      {isExpanded && (
        <div className="flex flex-col space-y-3 mt-3">
          <div>
            <label className="text-sm">Version:</label>
            <select
              value={selectedVersion}
              onChange={(e) => onSelectVersion(e.target.value)}
              className="w-full bg-gray-800 p-2 rounded text-sm"
            >
              <option value="">-- Select a version --</option>
              {versions.map((v) => (
                <option key={v.version} value={v.version}>
                  v{v.version}{!v.has_annotations ? " (no annotations)" : ""}
                </option>
              ))}
            </select>
            {versions.length === 0 && (
              <p className="text-xs text-gray-400 mt-1">No prior reviewed versions found for this shot.</p>
            )}
          </div>

          <div>
            <label className="text-sm">Ghost Color:</label>
            <input
              type="color"
              value={config.color}
              onChange={(e) => handleChange("color", e.target.value)}
              className="w-full h-10 bg-gray-800 rounded"
            />
          </div>

          {/* Enable Comparison Checkbox */}
          <label className="flex items-center space-x-2 mt-2 text-sm">
            <input
              type="checkbox"
              checked={config.enabled}
              onChange={(e) => handleChange("enabled", e.target.checked)}
              disabled={!selectedVersion}
              className="cursor-pointer"
            />
            <span>Show Comparison</span>
          </label>
        </div>
      )}
    </div>
  );
}
