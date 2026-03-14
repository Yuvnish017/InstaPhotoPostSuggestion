import psutil
import time
import threading
from db import save_telemetry  # You'll need to create this
from logger import Logger

LOGGER = Logger(log_file_name="resource_monitor.log")


class ResourceMonitor(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.sampling_interval = 60  # Default: 1 minute
        self.is_analyzing = False

    def set_high_priority(self, active: bool):
        # When analyzing, sample every 2 seconds to catch the spike
        self.sampling_interval = 2 if active else 60
        self.is_analyzing = active
        LOGGER.info(f"Sampling interval set to: {self.sampling_interval}")

    def run(self):
        while True:
            stats = {
                "cpu": psutil.cpu_percent(),
                "mem": psutil.Process().memory_info().rss / (1024 * 1024),
                "temp": self.get_pi_temp(),  # Critical for Pi 4!
                "is_busy": self.is_analyzing  # Track if we were analyzing photos
            }
            LOGGER.info(f"Utilization and temp stats: {str(stats)}")

            # Save to DB only if we are in high-priority mode or every hour
            if self.is_analyzing or (time.time() % 3600 < self.sampling_interval):
                save_telemetry(stats)
                LOGGER.info("Saved stats to DB")

            LOGGER.info(f"Going into sleep mode for {self.sampling_interval}")
            time.sleep(self.sampling_interval)

    def get_pi_temp(self):
        # Raspberry Pi specific: Read the thermal sensor
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                return float(f.read()) / 1000
        except:
            return 0.0
