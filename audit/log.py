import json
import os
import threading


class AuditLog:
    def __init__(self, filepath: str = "audit_log.jsonl"):
        self._entries: list[dict] = []
        self._lock = threading.Lock()
        self._filepath = filepath
        self._load_from_file()

    def _load_from_file(self):
        if os.path.exists(self._filepath):
            with open(self._filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self._entries.append(json.loads(line))

    def _write_to_file(self, entry: dict):
        with open(self._filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def append(self, entry: dict):
        with self._lock:
            self._entries.append(entry)
            self._write_to_file(entry)

    def get_all(self) -> list[dict]:
        with self._lock:
            return list(self._entries)

    def get_by_id(self, content_id: str) -> dict | None:
        with self._lock:
            for entry in reversed(self._entries):
                if entry.get("content_id") == content_id and "event_type" not in entry:
                    return entry
        return None

    def update_status(self, content_id: str, status: str):
        with self._lock:
            for entry in self._entries:
                if entry.get("content_id") == content_id and "event_type" not in entry:
                    entry["status"] = status
                    break
