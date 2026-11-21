-- Add project_file_path column to projects table.
-- Stores the user-chosen .json path when they save a project with a custom filename.
-- Empty string means the default storage/projects/{id}.json is used.
ALTER TABLE projects ADD COLUMN project_file_path TEXT NOT NULL DEFAULT '';