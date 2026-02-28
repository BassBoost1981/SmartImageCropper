"""StatsCollector: Zähler, Timing, Erfolgsrate für Batch-Verarbeitung."""

import time


class StatsCollector:
    """Sammelt Statistiken während der Bildverarbeitung."""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.total: int = 0
        self.processed: int = 0
        self.skipped: int = 0
        self.errors: int = 0
        self.persons_found: int = 0
        self.watermarks_found: int = 0
        self._start_time: float = 0.0
        self._end_time: float = 0.0

    def start(self) -> None:
        self._start_time = time.time()
        self._end_time = 0.0

    def stop(self) -> None:
        self._end_time = time.time()

    @property
    def elapsed(self) -> float:
        if self._start_time == 0:
            return 0.0
        end = self._end_time if self._end_time > 0 else time.time()
        return end - self._start_time

    @property
    def speed(self) -> float:
        """Bilder pro Sekunde."""
        elapsed = self.elapsed
        if elapsed <= 0 or self.processed == 0:
            return 0.0
        return self.processed / elapsed

    @property
    def success_rate(self) -> float:
        """Erfolgsrate in Prozent."""
        if self.total == 0:
            return 0.0
        return (self.processed / self.total) * 100

    def eta_seconds(self) -> float:
        """Geschätzte verbleibende Zeit in Sekunden."""
        if self.speed <= 0:
            return 0.0
        remaining = self.total - self.processed - self.skipped - self.errors
        return max(0, remaining / self.speed)

    def summary(self) -> dict:
        return {
            "total": self.total,
            "processed": self.processed,
            "skipped": self.skipped,
            "errors": self.errors,
            "persons_found": self.persons_found,
            "watermarks_found": self.watermarks_found,
            "elapsed": round(self.elapsed, 1),
            "speed": round(self.speed, 2),
            "success_rate": round(self.success_rate, 1),
        }
