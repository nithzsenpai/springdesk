import json
import logging
import time

from app import build_report, database, initialize

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


def process_one():
    with database() as db:
        # Serialize the short report transaction across worker processes.
        db.execute("BEGIN IMMEDIATE")
        job = db.execute(
            """SELECT * FROM reports WHERE status = 'queued' AND available_at <= unixepoch()
               ORDER BY available_at, id LIMIT 1"""
        ).fetchone()
        if job is None:
            return False

        attempts = job["attempts"] + 1
        try:
            result = json.dumps(build_report(db, job["project_id"]))
        except Exception:
            logger.exception("Report %s failed on attempt %s", job["id"], attempts)
            status = "failed" if attempts >= MAX_ATTEMPTS else "queued"
            db.execute(
                "UPDATE reports SET attempts = ?, status = ?, available_at = unixepoch() + ? WHERE id = ?",
                (attempts, status, 2 ** attempts, job["id"]),
            )
        else:
            db.execute(
                "UPDATE reports SET attempts = ?, status = 'ready', result = ? WHERE id = ?",
                (attempts, result, job["id"]),
            )
        return True


def main():
    logging.basicConfig(level=logging.INFO)
    initialize()
    logger.info("Report worker started")
    while True:
        try:
            if process_one():
                continue
        except Exception:
            logger.exception("Queue transaction failed")
        time.sleep(1)


if __name__ == "__main__":
    main()
