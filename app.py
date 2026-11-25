import json
import os
import sqlite3
from collections import Counter
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StringConstraints

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("SPRINTDESK_DB", ROOT / "data" / "sprintdesk.sqlite3"))
Status = Literal["Backlog", "In progress", "Done"]
Priority = Literal["Low", "Medium", "High"]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=3000)]
Assignee = Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)]


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title
    description: Description = ""


class StoryInput(ProjectInput):
    status: Status = "Backlog"
    priority: Priority = "Medium"


class TaskInput(ProjectInput):
    status: Status = "Backlog"
    assignee: Assignee = ""


class Project(ProjectInput):
    id: int


class Task(TaskInput):
    id: int
    story_id: int


class Story(StoryInput):
    id: int
    project_id: int
    tasks: list[Task]


class Board(Project):
    stories: list[Story]


class Report(BaseModel):
    id: int
    project_id: int
    status: Literal["queued", "ready", "failed"]
    attempts: int
    created_at: int
    result: dict[str, dict[str, int]] | None


@contextmanager
def database():
    connection = sqlite3.connect(DB, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            yield connection
    finally:
        connection.close()


def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with database() as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript((ROOT / "schema.sql").read_text())


@asynccontextmanager
async def lifespan(_app):
    initialize()
    yield


app = FastAPI(title="Sprintdesk API", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "static" / "index.html")


def get_row(db, table, item_id):
    # Table names come exclusively from route code.
    row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Item not found")
    return dict(row)


def insert(db, table, values):
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    cursor = db.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values()))
    return get_row(db, table, cursor.lastrowid)


def replace(db, table, item_id, data):
    values = data.model_dump()
    assignments = ", ".join(f"{column} = ?" for column in values)
    db.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", (*values.values(), item_id))
    return get_row(db, table, item_id)


def story_with_tasks(db, story):
    story["tasks"] = [
        dict(row) for row in db.execute("SELECT * FROM tasks WHERE story_id = ? ORDER BY id", (story["id"],))
    ]
    return story


@app.get("/api/projects", response_model=list[Project])
def projects():
    with database() as db:
        return [dict(row) for row in db.execute("SELECT * FROM projects ORDER BY id")]


@app.post("/api/projects", response_model=Project, status_code=201)
def create_project(data: ProjectInput):
    with database() as db:
        return insert(db, "projects", data.model_dump())


@app.get("/api/projects/{project_id}", response_model=Board)
def board(project_id: int):
    with database() as db:
        db.execute("BEGIN")
        project = get_row(db, "projects", project_id)
        stories = {
            row["id"]: {**dict(row), "tasks": []}
            for row in db.execute("SELECT * FROM stories WHERE project_id = ? ORDER BY id", (project_id,))
        }
        tasks = db.execute(
            "SELECT t.* FROM tasks t JOIN stories s ON s.id = t.story_id WHERE s.project_id = ? ORDER BY t.id",
            (project_id,),
        )
        for task in tasks:
            stories[task["story_id"]]["tasks"].append(dict(task))
        return {**project, "stories": list(stories.values())}


@app.put("/api/projects/{project_id}", response_model=Project)
def update_project(project_id: int, data: ProjectInput):
    with database() as db:
        return replace(db, "projects", project_id, data)


@app.post("/api/projects/{project_id}/stories", response_model=Story, status_code=201)
def create_story(project_id: int, data: StoryInput):
    with database() as db:
        get_row(db, "projects", project_id)
        return {**insert(db, "stories", {"project_id": project_id, **data.model_dump()}), "tasks": []}


@app.put("/api/stories/{story_id}", response_model=Story)
def update_story(story_id: int, data: StoryInput):
    with database() as db:
        return story_with_tasks(db, replace(db, "stories", story_id, data))


@app.post("/api/stories/{story_id}/tasks", response_model=Task, status_code=201)
def create_task(story_id: int, data: TaskInput):
    with database() as db:
        get_row(db, "stories", story_id)
        return insert(db, "tasks", {"story_id": story_id, **data.model_dump()})


@app.put("/api/tasks/{task_id}", response_model=Task)
def update_task(task_id: int, data: TaskInput):
    with database() as db:
        return replace(db, "tasks", task_id, data)


def report_response(row):
    return {**dict(row), "result": json.loads(row["result"]) if row["result"] else None}


@app.post("/api/projects/{project_id}/reports", response_model=Report, status_code=202)
def queue_report(project_id: int):
    with database() as db:
        get_row(db, "projects", project_id)
        return report_response(insert(db, "reports", {"project_id": project_id}))


@app.get("/api/projects/{project_id}/reports", response_model=list[Report])
def reports(project_id: int):
    with database() as db:
        get_row(db, "projects", project_id)
        return [
            report_response(row) for row in db.execute(
                "SELECT * FROM reports WHERE project_id = ? ORDER BY id DESC LIMIT 20", (project_id,)
            )
        ]


@app.get("/api/reports/{report_id}", response_model=Report)
def report(report_id: int):
    with database() as db:
        return report_response(get_row(db, "reports", report_id))


def build_report(db, project_id):
    stories = db.execute("SELECT status FROM stories WHERE project_id = ?", (project_id,))
    tasks = db.execute(
        "SELECT t.status FROM tasks t JOIN stories s ON t.story_id = s.id WHERE s.project_id = ?",
        (project_id,),
    )
    return {
        "stories": dict(Counter(row["status"] for row in stories)),
        "tasks": dict(Counter(row["status"] for row in tasks)),
    }
