"""Per-run JSONL trace: every step the agent took, kept for inspection."""
import json, time

class Trace:
    def __init__(self, path):
        self.path = path
        self._f = open(path, "a", encoding="utf-8")

    def log(self, kind, **detail):
        self._f.write(json.dumps({"ts": round(time.time(), 3), "kind": kind, **detail}) + "\n")
        self._f.flush()

    def close(self):
        self._f.close()
