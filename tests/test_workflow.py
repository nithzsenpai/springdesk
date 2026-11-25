import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app
import worker


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(app, "DB", Path(directory) / "test.sqlite3"))
        self.client = self.enterContext(TestClient(app.app))
        response = self.client.post("/api/projects", json={"title": "Website"})
        self.assertEqual(response.status_code, 201)
        self.project = "/api/projects/" + str(response.json()["id"])

    def test_hierarchy_and_report(self):
        story = self.client.post(self.project + "/stories", json={"title": "Account settings"})
        self.assertEqual(story.status_code, 201)
        story_path = "/api/stories/" + str(story.json()["id"])
        task = self.client.post(story_path + "/tasks", json={"title": "Save preferences"})
        self.assertEqual(task.status_code, 201)
        update = self.client.put(
            "/api/tasks/" + str(task.json()["id"]),
            json={"title": "Save preferences", "status": "Done", "assignee": "Asha"},
        )
        self.assertEqual(update.status_code, 200)
        board = self.client.get(self.project).json()
        self.assertEqual(board["stories"][0]["tasks"][0]["assignee"], "Asha")
        self.assertEqual(self.client.post("/api/stories/999/tasks", json={"title": "Missing"}).status_code, 404)
        self.assertEqual(
            self.client.post(self.project + "/stories", json={"title": "x", "status": "invalid"}).status_code,
            422,
        )

        queued = self.client.post(self.project + "/reports")
        self.assertEqual(queued.status_code, 202)
        self.assertEqual(queued.json()["status"], "queued")
        self.assertTrue(worker.process_one())
        self.assertFalse(worker.process_one())
        report = self.client.get("/api/reports/" + str(queued.json()["id"])).json()
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["result"], {"stories": {"Backlog": 1}, "tasks": {"Done": 1}})

    def test_retry_delay_and_terminal_failure(self):
        queued = self.client.post(self.project + "/reports").json()
        path = "/api/reports/" + str(queued["id"])
        with patch.object(worker, "build_report", side_effect=RuntimeError("simulated")), self.assertLogs(
            worker.logger, "ERROR"
        ):
            for attempt in range(1, 4):
                self.assertTrue(worker.process_one())
                self.assertFalse(worker.process_one())
                report = self.client.get(path).json()
                self.assertEqual(report["attempts"], attempt)
                self.assertEqual(report["status"], "queued" if attempt < 3 else "failed")
                with app.database() as db:
                    db.execute("UPDATE reports SET available_at = 0 WHERE id = ?", (queued["id"],))
