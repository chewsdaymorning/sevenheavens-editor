"""One local worker with persisted transitions and cooperative cancellation."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from typing import Callable

from .contracts import Job, now
from .store import Store


class JobCancelled(Exception):
    pass


class JobManager:
    def __init__(self, store: Store):
        self.store = store
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sevenheavens")
        self.events: dict[str, Event] = {}
        self.lock = Lock()
        for record in store.list("jobs"):
            job = Job.model_validate(record)
            if job.status in {"queued", "running"}:
                job.status = "needs_attention"
                job.error = "Application stopped during this attempt. Inspect artifacts before retrying; no automatic resubmission."
                job.updated_at = now()
                store.put("jobs", job)

    def save(self, job: Job):
        job.updated_at = now()
        self.store.put("jobs", job)

    def submit(self, job: Job, function: Callable) -> Job:
        event = Event()
        with self.lock:
            self.events[job.id] = event
        self.save(job)

        def execute():
            try:
                if event.is_set():
                    raise JobCancelled()
                job.status = "running"
                job.attempts += 1
                self.save(job)

                def progress(value: float, stage: str | None = None):
                    if event.is_set():
                        raise JobCancelled()
                    job.progress = max(0, min(1, value))
                    if stage:
                        job.stage = stage
                    self.save(job)

                result = function(event.is_set, progress)
                if event.is_set():
                    raise JobCancelled()
                job.artifacts = result or {}
                job.progress = 1
                job.status = "succeeded"
            except JobCancelled:
                job.status = "cancelled"
                job.error = "Cancelled; previous completed output versions remain intact."
            except Exception as exc:
                job.status = "cancelled" if event.is_set() else "failed"
                job.error = str(exc)
            finally:
                self.save(job)
                with self.lock:
                    self.events.pop(job.id, None)

        self.pool.submit(execute)
        return job

    def cancel(self, job_id: str) -> dict | None:
        record = self.store.get("jobs", job_id)
        if record is None:
            return None
        with self.lock:
            event = self.events.get(job_id)
            if event:
                event.set()
        if record["status"] in {"blocked", "queued", "needs_attention"}:
            record["status"] = "cancelled"
            record["updated_at"] = now()
            self.store.put("jobs", record)
        return self.store.get("jobs", job_id)

    def close(self):
        with self.lock:
            for event in self.events.values():
                event.set()
        self.pool.shutdown(wait=True, cancel_futures=False)
