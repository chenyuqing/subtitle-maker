from __future__ import annotations

import unittest

from subtitle_maker.jobs import TaskStore


class TaskStoreTests(unittest.TestCase):
    def test_create_get_and_copy_keep_behavior_consistent(self) -> None:
        store = TaskStore()
        payload = {"id": "task_001", "status": "queued", "stdout_tail": []}

        store.create("task_001", payload)
        self.assertIs(store.get("task_001"), payload)

        copied = store.get_copy("task_001")
        self.assertEqual(copied, payload)
        self.assertIsNot(copied, payload)

    def test_update_and_active_listing_respect_terminal_status(self) -> None:
        store = TaskStore()
        store.create("running_task", {"status": "running"})
        store.create("done_task", {"status": "completed"})

        self.assertEqual(store.list_active_ids(), ["running_task"])
        store.update("running_task", status="failed")
        self.assertEqual(store.list_active_ids(), [])

    def test_items_snapshot_returns_task_copies(self) -> None:
        store = TaskStore()
        store.create("task_001", {"status": "queued", "progress": 0.0})

        snapshot = store.items_snapshot()
        self.assertEqual(snapshot, [("task_001", {"status": "queued", "progress": 0.0})])
        self.assertIsNot(snapshot[0][1], store.get("task_001"))

    def test_append_stdout_and_public_view_keep_runtime_contract(self) -> None:
        store = TaskStore()
        store.create(
            "task_001",
            {
                "status": "running",
                "stdout_tail": [],
                "input_path": "/tmp/input.wav",
                "out_root": "/tmp/out",
                "upload_dir": "/tmp/upload",
                "process": object(),
            },
        )

        for index in range(125):
            store.append_stdout("task_001", f"line-{index}")

        task = store.get("task_001")
        assert task is not None
        self.assertEqual(len(task["stdout_tail"]), 120)
        self.assertEqual(task["stdout_tail"][0], "line-5")

        public = store.get_public("task_001")
        assert public is not None
        self.assertNotIn("input_path", public)
        self.assertNotIn("out_root", public)
        self.assertNotIn("upload_dir", public)
        self.assertNotIn("process", public)
        self.assertEqual(public["stdout_tail"][-1], "line-124")

    def test_set_stage_never_rolls_back_progress(self) -> None:
        store = TaskStore()
        store.create("task_001", {"status": "running", "stage": "queued", "progress": 40.0})

        store.set_stage("task_001", "transcribing", 12.0, updated_at="2026-04-24T00:00:00Z")
        task = store.get("task_001")
        assert task is not None
        self.assertEqual(task["stage"], "transcribing")
        self.assertEqual(task["progress"], 40.0)
        self.assertEqual(task["updated_at"], "2026-04-24T00:00:00Z")

        store.set_stage("task_001", "dubbing", 68.0, updated_at="2026-04-24T00:01:00Z")
        self.assertEqual(task["stage"], "dubbing")
        self.assertEqual(task["progress"], 68.0)
        self.assertEqual(task["updated_at"], "2026-04-24T00:01:00Z")


if __name__ == "__main__":
    unittest.main()
