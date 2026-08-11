-- Users Table

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    login_name TEXT NOT NULL,
    email TEXT NOT NULL,
    password_hash TEXT,                    -- For securely storing hashed passwords
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,  -- Automatically sets creation time
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP  -- Automatically sets last update time
);

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS user_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id),
    FOREIGN KEY (group_id) REFERENCES groups (id)
    UNIQUE (user_id, group_id)
);


CREATE TABLE IF NOT EXISTS class_enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    semester TEXT NOT NULL,
    FOREIGN KEY (class_id) REFERENCES classes(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_name TEXT NOT NULL,
    year INTEGER NOT NULL CHECK(year IN (2025, 2026, 2027, 2028, 2029, 2030)),
    semester TEXT NOT NULL CHECK(semester IN ('Fall', 'Spring', 'Summer')),
    code TEXT NOT NULL CHECK(code IN ('GAA', 'FAA', 'DMC')),
    class_number INTEGER NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS class_students (
    class_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    PRIMARY KEY (class_id, student_id),
    FOREIGN KEY (class_id) REFERENCES classes (id),
    FOREIGN KEY (student_id) REFERENCES users (id)
);


-- Assignments Table---------------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    completion_date TEXT NOT NULL,
    frame_start INTEGER,
    frame_end INTEGER,
    max_points INTEGER,
    FOREIGN KEY (class_id) REFERENCES classes (id)
);

CREATE TABLE IF NOT EXISTS assignment_students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    UNIQUE (assignment_id, student_id),  -- Prevent duplicate assignments
    FOREIGN KEY (assignment_id) REFERENCES assignments(id),
    FOREIGN KEY (student_id) REFERENCES users(id)
);


CREATE TABLE IF NOT EXISTS individual_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    start_date DATE,
    completion_date DATE,
    grade TEXT,
    feedback TEXT,
    FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE,
    FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Films Table----------------------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS films (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    writer TEXT NOT NULL,
    director TEXT NOT NULL
);

CREATE TABLE "projects" (
    "id" INTEGER,
    "film_id" INTEGER NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "due_date" DATE,
    PRIMARY KEY("id" AUTOINCREMENT),
    FOREIGN KEY("film_id") REFERENCES "films"("id") ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS sequences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    sequence_number INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS shots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sequence_id INTEGER NOT NULL,
    shot_number TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'not started' CHECK(status IN ('not started', 'in progress', 'completed')),
    due_date DATE,
    FOREIGN KEY (sequence_id) REFERENCES sequences(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Nodes --------------------------------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,               -- Name of the node (e.g., Assignment Basic Task)
    task_id INTEGER NOT NULL,         -- Link to the parent task/assignment
    position INTEGER NOT NULL,        -- Order of the node in the workflow
    status TEXT NOT NULL DEFAULT 'Standby', -- Current status of the node
    completion_percentage INTEGER DEFAULT 0, -- Completion progress (e.g., 0%, 50%, 100%)
    color TEXT DEFAULT NULL,          -- Color for visual UI
    dependency_id INTEGER DEFAULT NULL, -- Reference to another node it depends on
    FOREIGN KEY (task_id) REFERENCES tasks (id),
    FOREIGN KEY (dependency_id) REFERENCES nodes (id)
);

CREATE TABLE IF NOT EXISTS statuses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER NOT NULL,         -- Reference to the node
    status_name TEXT NOT NULL,        -- Name of the status (e.g., Standby, Grading)
    color TEXT DEFAULT NULL,          -- Optional color for UI
    FOREIGN KEY (node_id) REFERENCES nodes (id)
);

CREATE TABLE IF NOT EXISTS node_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_node_id INTEGER NOT NULL,  -- Node that triggers the dependency
    parent_status TEXT NOT NULL,      -- Status in the parent node (e.g., 'Completed')
    child_node_id INTEGER NOT NULL,   -- Node affected by the dependency
    child_status TEXT NOT NULL,       -- Status to set in the child node (e.g., 'In Progress')
    FOREIGN KEY (parent_node_id) REFERENCES nodes (id),
    FOREIGN KEY (child_node_id) REFERENCES nodes (id)
);


-- Indexes for Performance ----------------------------------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_assignment_class_id ON assignments(class_id);
CREATE INDEX IF NOT EXISTS idx_individual_assignment_assignment_id ON individual_assignments(assignment_id);
CREATE INDEX IF NOT EXISTS idx_projects_film_id ON projects(film_id);
CREATE INDEX IF NOT EXISTS idx_sequences_project_id ON sequences(project_id);
CREATE INDEX IF NOT EXISTS idx_shots_sequence_id ON shots(sequence_id);
CREATE INDEX IF NOT EXISTS idx_nodes_task_id ON nodes(task_id);
CREATE INDEX IF NOT EXISTS idx_classes_year ON classes ("year");
CREATE INDEX IF NOT EXISTS idx_classes_semester ON classes ("semester");
