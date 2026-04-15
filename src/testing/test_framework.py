import copy
import statistics
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from Ammeters.client import request_current_from_ammeter
from ..storage.sqlite_repository import SQLiteResultRepository
from ..utils.config import load_config
from ..utils.logger import TestLogger


class AmmeterTestFramework:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config_path = config_path
        self.config = load_config(config_path)
        self.repository = SQLiteResultRepository(self._database_path())

    def run_test(
        self,
        ammeter_type: str,
        measurements_count: Optional[int] = None,
        total_duration_seconds: Optional[float] = None,
        sampling_frequency_hz: Optional[float] = None,
    ) -> Dict[str, Any]:
        ammeter_key = ammeter_type.strip().lower()
        ammeter_config = self._get_ammeter_config(ammeter_key)
        sampling_config = self._resolve_sampling_config(
            measurements_count=measurements_count,
            total_duration_seconds=total_duration_seconds,
            sampling_frequency_hz=sampling_frequency_hz,
        )

        # Run IDs include UTC timestamp, meter key, and a short random suffix.
        test_run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{ammeter_key}_{uuid.uuid4().hex[:8]}"
        logger = TestLogger(test_run_id)
        logger.info(
            f"Starting test run {test_run_id} | ammeter={ammeter_key} | "
            f"count={sampling_config['measurements_count']} | "
            f"duration={sampling_config['total_duration_seconds']}s | "
            f"frequency={sampling_config['sampling_frequency_hz']}Hz"
        )

        command_bytes = ammeter_config["command"].encode("utf-8")
        port = int(ammeter_config["port"])

        sample_rows: List[Dict[str, Any]] = []
        interval_seconds = 1.0 / sampling_config["sampling_frequency_hz"]
        expected_count = sampling_config["measurements_count"]

        monotonic_start = time.monotonic()
        wall_clock_start = datetime.now(timezone.utc)
        for sample_index in range(expected_count):
            # Deadline scheduling reduces cumulative drift during long sample sequences.
            target_time = monotonic_start + (sample_index * interval_seconds)
            remaining = target_time - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)

            measured_current = request_current_from_ammeter(port, command_bytes)
            captured_at_seconds = time.monotonic() - monotonic_start
            sample_rows.append(
                {
                    "sample_index": sample_index + 1,
                    "captured_at_seconds": round(captured_at_seconds, 6),
                    "current_amps": measured_current,
                }
            )

        actual_duration_seconds = max(time.monotonic() - monotonic_start, 0.0)
        current_values = [float(row["current_amps"]) for row in sample_rows]
        statistics_result = self._calculate_statistics(current_values)

        result = {
            "test_run_id": test_run_id,
            "timestamp_utc": wall_clock_start.isoformat(),
            "metadata": {
                "ammeter_type": ammeter_key,
                "connection": {
                    "host": "localhost",
                    "port": port,
                    "command": ammeter_config["command"],
                },
                "sampling": sampling_config,
                "actual_duration_seconds": round(actual_duration_seconds, 6),
                "config_snapshot": copy.deepcopy(self.config),
            },
            "samples": sample_rows,
            "statistics": statistics_result,
        }

        self.repository.save_result(result)
        logger.info(f"Saved test run to sqlite database at {self._database_path()}")
        return result

    def load_result(self, test_run_id: str) -> Dict[str, Any]:
        return self.repository.get_result(test_run_id)

    def list_historical_results(
        self, ammeter_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        normalized = ammeter_type.strip().lower() if ammeter_type is not None else None
        return self.repository.list_results(
            ammeter_type=normalized, include_samples=False
        )

    def compare_runs(self, first_run_id: str, second_run_id: str) -> Dict[str, Any]:
        first_result = self.load_result(first_run_id)
        second_result = self.load_result(second_run_id)
        stats_keys = ["mean", "median", "stdev", "min", "max"]
        metric_deltas = {}
        for key in stats_keys:
            second_value = self._read_stat_value(second_result, key, second_run_id)
            first_value = self._read_stat_value(first_result, key, first_run_id)
            delta = second_value - first_value
            metric_deltas[key] = round(delta, 6)

        return {
            "first_run_id": first_run_id,
            "second_run_id": second_run_id,
            "first_ammeter": first_result.get("metadata", {}).get(
                "ammeter_type", "unknown"
            ),
            "second_ammeter": second_result.get("metadata", {}).get(
                "ammeter_type", "unknown"
            ),
            "metric_deltas": metric_deltas,
        }

    @staticmethod
    def _read_stat_value(result: Dict[str, Any], key: str, run_id: str) -> float:
        statistics_map = result.get("statistics")
        if not isinstance(statistics_map, dict):
            raise ValueError(f"Run '{run_id}' is missing a valid statistics object.")
        if key not in statistics_map:
            raise ValueError(f"Run '{run_id}' is missing statistics key '{key}'.")

        try:
            return float(statistics_map[key])
        except (TypeError, ValueError) as parse_error:
            raise ValueError(
                f"Run '{run_id}' has non-numeric value for statistics key '{key}'."
            ) from parse_error

    def _get_ammeter_config(self, ammeter_key: str) -> Dict[str, Any]:
        ammeters = self.config.get("ammeters", {})
        if ammeter_key not in ammeters:
            available = ", ".join(sorted(ammeters.keys()))
            raise ValueError(
                f"Unknown ammeter type '{ammeter_key}'. Available: {available}"
            )

        ammeter_config = ammeters[ammeter_key]
        if "port" not in ammeter_config or "command" not in ammeter_config:
            raise ValueError(
                f"Invalid ammeter configuration for '{ammeter_key}': expected port and command"
            )
        return ammeter_config

    def _resolve_sampling_config(
        self,
        measurements_count: Optional[int],
        total_duration_seconds: Optional[float],
        sampling_frequency_hz: Optional[float],
    ) -> Dict[str, Any]:
        sampling_defaults = self.config.get("testing", {}).get("sampling", {})
        default_count = sampling_defaults.get("measurements_count")
        default_duration = sampling_defaults.get("total_duration_seconds")
        default_frequency = sampling_defaults.get("sampling_frequency_hz")

        provided_count = measurements_count is not None
        provided_duration = total_duration_seconds is not None
        provided_frequency = sampling_frequency_hz is not None
        provided_values = (
            int(provided_count) + int(provided_duration) + int(provided_frequency)
        )

        count: Optional[int] = measurements_count
        duration: Optional[float] = total_duration_seconds
        frequency: Optional[float] = sampling_frequency_hz

        if provided_values == 0:
            count = default_count
            duration = default_duration
            frequency = default_frequency
        elif provided_values == 1:
            if provided_duration:
                # Duration-only override should control runtime length.
                frequency = (
                    float(default_frequency) if default_frequency is not None else 1.0
                )
                count = max(int(round(float(duration) * float(frequency))), 1)
            elif provided_count:
                if default_frequency is not None:
                    frequency = float(default_frequency)
                    duration = float(count) / float(frequency)
                elif default_duration is not None:
                    duration = float(default_duration)
                    frequency = float(count) / float(duration)
                else:
                    frequency = 1.0
                    duration = float(count)
            elif provided_frequency:
                count = int(default_count) if default_count is not None else 10
                duration = float(count) / float(frequency)
        else:
            # Two-or-more explicit values: derive only the missing dimension.
            if count is None and duration is not None and frequency is not None:
                count = max(int(round(float(duration) * float(frequency))), 1)
            elif duration is None and count is not None and frequency is not None:
                duration = float(count) / float(frequency)
            elif frequency is None and count is not None and duration is not None:
                frequency = float(count) / float(duration)

        if count is None:
            count = 10
        if duration is None:
            duration = float(count)
        if frequency is None:
            frequency = 1.0

        if int(count) <= 0:
            raise ValueError("measurements_count must be a positive integer.")
        if float(duration) <= 0:
            raise ValueError("total_duration_seconds must be greater than zero.")
        if float(frequency) <= 0:
            raise ValueError("sampling_frequency_hz must be greater than zero.")

        expected_duration = float(count) / float(frequency)
        if abs(expected_duration - float(duration)) > 0.1:
            # Normalize duration if provided values are inconsistent beyond tolerance.
            duration = expected_duration

        return {
            "measurements_count": int(count),
            "total_duration_seconds": round(float(duration), 6),
            "sampling_frequency_hz": round(float(frequency), 6),
        }

    @staticmethod
    def _calculate_statistics(values: List[float]) -> Dict[str, float]:
        if not values:
            raise ValueError("Cannot calculate statistics for an empty sample set.")

        return {
            "mean": round(statistics.fmean(values), 6),
            "median": round(statistics.median(values), 6),
            "stdev": round(statistics.stdev(values), 6) if len(values) > 1 else 0.0,
            "min": round(min(values), 6),
            "max": round(max(values), 6),
        }

    def reload_config(self) -> Dict[str, Any]:
        self.config = load_config(self.config_path)
        self.repository = SQLiteResultRepository(self._database_path())
        return self.config

    def _database_path(self) -> str:
        return (
            self.config.get("result_management", {}).get("database_path")
            or "results/ammeter_results.db"
        )
