"""文件上传 manifest 追踪，避免重复上传。"""

from __future__ import annotations

import json
from pathlib import Path

MANIFEST_NAME = "_manifest.json"


class Manifest:
    """管理上传记录的 manifest 文件。

    用法::

        manifest = Manifest(directory / MANIFEST_NAME)
        if not manifest.contains("file.json"):
            # ... 上传 ...
            manifest.update({"file.json": 42})
            manifest.save()
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, int] = {}
        if path.exists():
            with open(path, encoding="utf-8") as f:
                self._data = json.load(f)

    def contains(self, filename: str) -> bool:
        return filename in self._data

    def update(self, entries: dict[str, int]) -> None:
        self._data.update(entries)

    def save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
