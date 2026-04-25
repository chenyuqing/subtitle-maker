from __future__ import annotations

from threading import RLock
from typing import Any, Dict, List, Optional, Tuple

from .models import PublicJobRecord, TaskPayload

_PUBLIC_HIDDEN_FIELDS = {"process", "input_path", "out_root", "upload_dir"}


class TaskStore:
    """线程安全的内存任务存储。

    第一阶段只做 Auto Dubbing 任务收口，不改变现有内存存储语义。
    """

    def __init__(self) -> None:
        self._items: Dict[str, TaskPayload] = {}
        self._lock = RLock()

    @property
    def items(self) -> Dict[str, TaskPayload]:
        """暴露底层字典，兼容现有测试与少量旧代码。"""

        return self._items

    @property
    def lock(self) -> RLock:
        """暴露共享锁，兼容现有 `with _lock:` 代码块。"""

        return self._lock

    def clear(self) -> None:
        """清空全部任务。"""

        with self._lock:
            self._items.clear()

    def create(self, task_id: str, payload: TaskPayload) -> TaskPayload:
        """创建或覆盖任务记录。"""

        with self._lock:
            self._items[task_id] = payload
            return payload

    def get(self, task_id: str) -> Optional[TaskPayload]:
        """返回任务原始引用。"""

        with self._lock:
            return self._items.get(task_id)

    def get_copy(self, task_id: str) -> Optional[TaskPayload]:
        """返回任务浅拷贝，避免调用方误改共享状态。"""

        with self._lock:
            task = self._items.get(task_id)
            return dict(task) if task else None

    def update(self, task_id: str, **updates: Any) -> Optional[TaskPayload]:
        """局部更新任务。"""

        with self._lock:
            task = self._items.get(task_id)
            if task is None:
                return None
            task.update(updates)
            return task

    def append_stdout(self, task_id: str, line: str, *, limit: int = 120) -> Optional[TaskPayload]:
        """向任务追加 stdout tail，并限制最大保留行数。"""

        with self._lock:
            task = self._items.get(task_id)
            if task is None:
                return None
            tail = task.setdefault("stdout_tail", [])
            tail.append(line)
            if len(tail) > limit:
                del tail[:-limit]
            return task

    def set_stage(
        self,
        task_id: str,
        stage: str,
        minimum_progress: float,
        *,
        updated_at: Optional[str] = None,
    ) -> Optional[TaskPayload]:
        """在不回退进度的前提下更新任务阶段。"""

        with self._lock:
            task = self._items.get(task_id)
            if task is None:
                return None
            task["stage"] = stage
            task["progress"] = max(float(task.get("progress", 0.0) or 0.0), minimum_progress)
            if updated_at is not None:
                task["updated_at"] = updated_at
            return task

    def keys_snapshot(self) -> List[str]:
        """返回当前任务 ID 快照。"""

        with self._lock:
            return list(self._items.keys())

    def items_snapshot(self) -> List[Tuple[str, TaskPayload]]:
        """返回 `(task_id, task_copy)` 快照列表。"""

        with self._lock:
            return [(task_id, dict(task)) for task_id, task in self._items.items()]

    def list_active_ids(self, *, terminal_statuses: Optional[set[str]] = None) -> List[str]:
        """列出处于非终态的任务 ID。"""

        terminal = terminal_statuses or {"completed", "failed", "cancelled"}
        with self._lock:
            return [
                task_id
                for task_id, task in self._items.items()
                if str(task.get("status") or "") not in terminal
            ]

    def to_public(self, task: TaskPayload) -> PublicJobRecord:
        """将任务记录转换为公开视图，并隐藏本地敏感字段。"""

        public = {
            key: value
            for key, value in task.items()
            if key not in _PUBLIC_HIDDEN_FIELDS
        }
        public.setdefault("artifacts", [])
        return public

    def get_public(self, task_id: str) -> Optional[PublicJobRecord]:
        """读取公开任务视图快照。"""

        with self._lock:
            task = self._items.get(task_id)
            if task is None:
                return None
            public = {
                key: value
                for key, value in task.items()
                if key not in _PUBLIC_HIDDEN_FIELDS
            }
            public.setdefault("artifacts", [])
            return public
