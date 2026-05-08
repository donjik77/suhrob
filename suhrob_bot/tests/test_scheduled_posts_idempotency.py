import inspect
import os
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")

from src.db.models import ScheduledPostStatus
from src.scheduler.jobs import job_publish_scheduled_posts


class ScheduledPostsIdempotencyTest(unittest.TestCase):
    def test_status_enum_has_in_progress(self):
        self.assertEqual(ScheduledPostStatus.in_progress.value, "in_progress")

    def test_publish_job_claims_pending_posts_with_row_lock(self):
        source = inspect.getsource(job_publish_scheduled_posts)

        self.assertIn("with_for_update(skip_locked=True)", source)
        self.assertIn("ScheduledPostStatus.pending", source)
        self.assertIn("ScheduledPostStatus.in_progress", source)
        self.assertIn("ScheduledPostStatus.published", source)
        self.assertIn("ScheduledPostStatus.failed", source)

    def test_migration_adds_in_progress_to_database_enum(self):
        migration = Path("alembic/versions/0005_add_scheduled_post_in_progress_status.py")

        self.assertTrue(migration.exists())
        self.assertIn(
            "ALTER TYPE scheduledpoststatus ADD VALUE IF NOT EXISTS 'in_progress'",
            migration.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
