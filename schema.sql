CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('Backlog', 'In progress', 'Done')),
    priority TEXT NOT NULL CHECK(priority IN ('Low', 'Medium', 'High'))
);
CREATE INDEX IF NOT EXISTS stories_project ON stories(project_id);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id INTEGER NOT NULL REFERENCES stories(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('Backlog', 'In progress', 'Done')),
    assignee TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_story ON tasks(story_id);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued', 'ready', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at INTEGER NOT NULL DEFAULT (unixepoch()),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    result TEXT
);
CREATE INDEX IF NOT EXISTS reports_queue ON reports(status, available_at, id);
CREATE INDEX IF NOT EXISTS reports_project ON reports(project_id, id);
