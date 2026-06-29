"""In-memory generation job registry for pause/resume/reconnect support.

Provides a singleton registry of GenerationJob objects that decouple
question generation from the SSE request lifecycle. Jobs run as
independent asyncio.Tasks and communicate via asyncio.Queue for events.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

# After how many seconds completed/terminated jobs are auto-removed
JOB_CLEANUP_DELAY = 30 * 60  # 30 minutes

JobStatus = Literal["pending", "running", "paused", "completed", "terminated", "error"]


@dataclass
class GenerationJob:
    """In-memory representation of a question generation job."""

    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: JobStatus = "pending"
    bank_name: str = ""
    bank_id: int | None = None
    total_planned: int = 0
    completed_count: int = 0
    questions: list[dict] = field(default_factory=list)
    current_stage: str = ""
    # Control flags
    pause_event: asyncio.Event = field(default_factory=lambda: asyncio.Event())
    terminate_flag: bool = False
    # Timestamps
    created_at: float = field(default_factory=time.time)
    error_message: str | None = None
    # Generation parameters (concurrency, batch_size, mode, etc.)
    generation_params: dict = field(default_factory=dict)
    # Event queue: SSE events to push to connected clients (bounded to prevent unbounded memory)
    event_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=500))
    # Past events buffer for reconnect replay
    past_events: list[dict] = field(default_factory=list)
    # asyncio.Task reference (set after creation)
    task: asyncio.Task | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        # asyncio.Event must be created inside a running loop in Python <3.10,
        # but our default factory handles it. Ensure pause is set (= running).
        self.pause_event.set()

    # -- helpers for the generation loop to call --

    def push_event(self, event: dict) -> None:
        """Record event in past_events buffer and enqueue for live consumers."""
        self.past_events.append(event)
        # Cap past_events to prevent unbounded memory growth
        from app.config import get_settings
        max_events = get_settings().job_max_past_events
        if len(self.past_events) > max_events:
            self.past_events = self.past_events[-max_events:]
        try:
            self.event_queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(f"Job {self.job_id} event queue full, dropping event type={event.get('type')}")

    def check_pause(self) -> None:
        """Coroutine: blocks if pause_event is cleared."""
        # This is meant to be awaited in the generation loop.
        # When pause_event is cleared, await returns only after it is set again.
        return self.pause_event.wait()

    def should_terminate(self) -> bool:
        return self.terminate_flag


class GenerationJobRegistry:
    """Singleton registry of all active generation jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, GenerationJob] = {}

    def create_job(self, **kwargs) -> GenerationJob:
        """Create and register a new job."""
        job = GenerationJob(**kwargs)
        self._jobs[job.job_id] = job
        logger.info(f"Created generation job {job.job_id} (bank_name={job.bank_name})")
        return job

    def get_job(self, job_id: str) -> GenerationJob | None:
        return self._jobs.get(job_id)

    def remove_job(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)
        logger.info(f"Removed generation job {job_id}")

    def list_jobs(self) -> list[GenerationJob]:
        return list(self._jobs.values())

    def schedule_cleanup(self, job_id: str, delay: float = JOB_CLEANUP_DELAY) -> None:
        """Schedule automatic removal of a finished job after *delay* seconds."""
        async def _cleanup() -> None:
            await asyncio.sleep(delay)
            self.remove_job(job_id)

        try:
            asyncio.create_task(_cleanup())
        except RuntimeError:
            # No running loop — cleanup will be skipped; acceptable for tests
            pass


# Module-level singleton
generation_registry = GenerationJobRegistry()
