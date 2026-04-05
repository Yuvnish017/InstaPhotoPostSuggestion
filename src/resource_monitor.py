"""Background resource sampler for CPU, memory and device temperature."""

import psutil
import time
import threading
from db import save_telemetry
from logger import Logger

LOGGER = Logger(log_file_name="resource_monitor.log")


class ResourceMonitor(threading.Thread):
    """Periodically samples runtime resource usage and stores telemetry."""

    _WAIT_SLICE_SEC = 0.25

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.sampling_interval = 60  # default cadence when idle
        self.is_analyzing = False

    def set_high_priority(self, active: bool) -> None:
        """Switch sampling cadence between idle and analysis modes."""
        # During heavy analysis, higher sampling gives better observability.
        self.sampling_interval = 2 if active else 60
        self.is_analyzing = active
        LOGGER.info(f"Sampling interval set to: {self.sampling_interval}")

    def _interruptible_sleep(self, total_seconds: float) -> None:
        """Sleep for up to total_seconds, but return as soon as set_high_priority() runs."""
        if total_seconds <= 0:
            return
        deadline = time.monotonic() + total_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(self._WAIT_SLICE_SEC)
            if self.is_analyzing:
                break

    def run(self) -> None:
        """Main thread loop. Collect metrics and persist snapshots."""
        while True:
            stats = {
                "cpu": psutil.cpu_percent(),
                "mem": psutil.Process().memory_info().rss / (1024 * 1024),
                "temp": self.get_pi_temp(),
                "is_busy": self.is_analyzing,
            }
            LOGGER.info(f"Utilization and temp stats: {str(stats)}")

            # Persist frequently while busy; otherwise persist a coarse hourly sample.
            if self.is_analyzing or (time.time() % 3600 < self.sampling_interval):
                save_telemetry(stats)
                LOGGER.info("Saved stats to DB")

            LOGGER.info(f"Going into sleep mode for {self.sampling_interval}")
            self._interruptible_sleep(float(self.sampling_interval))

    def get_pi_temp(self) -> float:
        """Read Raspberry Pi thermal sensor in Celsius.

        Returns 0.0 when running on platforms where the sensor path
        is unavailable.
        """
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8") as temp_file:
                return float(temp_file.read()) / 1000
        except (FileNotFoundError, PermissionError, ValueError):
            return 0.0
