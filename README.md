# Sprintdesk

Sprintdesk is a shared agile workspace for a small team. Create projects, organize user stories on a three-stage board, and assign and track tasks within each story. Request a progress report to keep a timestamped history of story and task counts by status.

## Run locally

Requires Python 3.12 or later and SQLite 3.38 or later. Run these commands from the repository root.

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app:app
```

On Windows PowerShell, use `.\.venv\Scripts\Activate.ps1` to activate the environment. In a second terminal, activate that same environment and run the report worker:

```sh
python worker.py
```

Open [Sprintdesk](http://127.0.0.1:8000) or [Swagger UI](http://127.0.0.1:8000/docs). The workspace starts empty. Both commands initialize the schema automatically. Set `SPRINTDESK_DB` to the same absolute file path in both terminals to override the default `data/sprintdesk.sqlite3`.

### Try the workflow

1. Create a project named **Customer Portal**.
2. Add a story named **Manage notification settings** with high priority.
3. Add a task called **Save email preferences** and assign it to a teammate by name.
4. Edit the story to move it to **In progress**. Edit the task to mark it **Done**.
5. Generate a report and open **Report history**. With the worker running, the report should move from queued to ready. Reload the page to verify persistence.

### Run the tests

```sh
python -m pip install httpx==0.28.1
python -m unittest discover -s tests -v
```

## Architecture and design decisions

The browser uses HTML, CSS and JavaScript served by FastAPI. Its requests use same-origin JSON endpoints. FastAPI validates inputs with Pydantic and runs parameterized SQL with Python's SQLite driver. A separate Python process reads the report queue in the same database.

A project board is fetched as one nested snapshot in a read transaction. The server batches the task query across the project. For a 3–10 person team, this keeps the interface and API simple. Large boards would need pagination or loading tasks on demand.

Stories use **Backlog → In progress → Done**. A story's state and its task completion are independent so the team can decide when the story meets its acceptance criteria. Use the story description to record those criteria. Tasks have free-text assignees, which keeps local setup simple and means names can differ in spelling. Existing items can be edited in place and remain attached to their original parent. Concurrent edits use last-write-wins semantics.

### Background reports

A request writes a durable queue row and returns HTTP 202. The worker picks the oldest eligible job. An immediate SQLite transaction covers job selection, status counts and the final update. Concurrent workers cannot complete the same row twice, and a process crash before commit rolls the transaction back, leaving the job eligible again. Report counts describe the project when the worker processes it. The displayed timestamp records when the report was requested.

Report computation errors are logged. The first two failures schedule retries after two and four seconds. The third sets a terminal failed status. Transaction-level errors roll back, are logged, and are retried by the polling loop. Failed reports remain visible, and users can request a fresh report. A stopped worker leaves reports queued. The UI polls while the newest 20 reports include queued work.

The design relies on bounded local queries and holds a write lock during report generation. It suits small datasets and avoids another service. Longer tasks would need a claim-and-lease workflow that releases the write lock during processing.

## Database schema

| Table | Fields beyond integer primary key | Constraints and indexes |
| --- | --- | --- |
| `projects` | title, description | Both required in storage |
| `stories` | project_id, title, description, status, priority | Indexed project foreign key and enum checks |
| `tasks` | story_id, title, description, status, assignee | Indexed story foreign key and status check |
| `reports` | project_id, status, attempts, available_at, created_at, result | Project foreign key, status check, queue and project-history indexes |

A project has zero or more stories. A story has zero or more tasks and each task belongs to exactly one story. Report timestamps are Unix seconds in UTC and results are stored as JSON text. SQLite foreign key enforcement is enabled per connection and write-ahead logging allows readers to proceed during writes. See [schema.sql](schema.sql) for the complete DDL.

## API documentation

Interactive API documentation is available at `/docs` and its machine-readable contract at `/openapi.json`. All paths below are relative to `/api`.

| Method | Path | Success | Purpose |
| --- | --- | --- | --- |
| GET | `/projects` | 200 | List projects |
| POST | `/projects` | 201 | Create project |
| GET | `/projects/{project_id}` | 200 | Read project, stories and nested tasks |
| PUT | `/projects/{project_id}` | 200 | Replace project fields |
| POST | `/projects/{project_id}/stories` | 201 | Add story to project |
| PUT | `/stories/{story_id}` | 200 | Replace story fields |
| POST | `/stories/{story_id}/tasks` | 201 | Add task to story |
| PUT | `/tasks/{task_id}` | 200 | Replace task fields |
| POST | `/projects/{project_id}/reports` | 202 | Queue a new progress report |
| GET | `/projects/{project_id}/reports` | 200 | List latest 20 reports |
| GET | `/reports/{report_id}` | 200 | Read one report's status and result |

Create and update bodies use JSON. Send all editable fields on PUT because omitted optional fields reset to their documented defaults. Titles are required. Description and assignee default to empty strings. Status defaults to `Backlog` and priority to `Medium`. Unknown fields or invalid values return 422. Missing resources return 404. A ready report contains two maps, `stories` and `tasks`, with counts keyed by status. An absent status has a count of zero.

## Security considerations

The server defaults to loopback and the app is a single trusted workspace. Anyone who can reach it can read and change its data. Before giving teammates remote access, add authentication and enforce membership on each resource, including report IDs. Serve over HTTPS behind a proxy that limits request size and rate, and restrict access to the SQLite data directory. Input fields are validated server-side and SQL values are bound as parameters. The browser inserts user content as text.

## AI usage

OpenAI Codex assisted with architecture, implementation, documentation and verification. The automated tests cover hierarchy, validation, report generation and retry handling.

## What I would improve or build next with more time

- Add sign-in, a team directory, per-project roles and an activity log.
- Add optimistic concurrency with item versions to catch conflicting edits.
- Add board filters, team workload views and pagination for busy projects.
- Add versioned migrations, scheduled backups and worker health metrics.
