import sys
import threading
import time
from pathlib import Path
from typing import Dict

# ruff: noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    # Ensure direct script execution resolves project imports
    # without requiring PYTHONPATH edits.
    sys.path.insert(0, str(PROJECT_ROOT))

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from src.testing.test_framework import AmmeterTestFramework
from src.utils.config import load_config

EMULATOR_CLASS_MAP: Dict[str, type] = {
    "greenlee": GreenleeAmmeter,
    "entes": EntesAmmeter,
    "circutor": CircutorAmmeter,
}


def _run_emulator(ammeter_class: type, port: int):
    emulator = ammeter_class(port)
    emulator.start_server()


def start_emulators():
    config = load_config(str(PROJECT_ROOT / "config" / "config.yaml"))
    for ammeter_name, ammeter_config in config.get("ammeters", {}).items():
        ammeter_key = str(ammeter_name).strip().lower()
        ammeter_class = EMULATOR_CLASS_MAP.get(ammeter_key)
        if ammeter_class is None:
            continue
        port = int(ammeter_config["port"])
        thread = threading.Thread(
            target=_run_emulator, args=(ammeter_class, port), daemon=True
        )
        thread.start()
    # Give sockets time to bind before framework requests begin.
    time.sleep(1.5)


def main():
    start_emulators()
    framework = AmmeterTestFramework()

    ammeter_types = ["greenlee", "entes", "circutor"]
    results = {}

    for ammeter_type in ammeter_types:
        print(f"Testing {ammeter_type} ammeter...")
        results[ammeter_type] = framework.run_test(ammeter_type)

    for ammeter_type, result in results.items():
        print(f"\nResults for {ammeter_type}:")
        stats = result["statistics"]
        print(
            f"Run ID={result['test_run_id']} "
            f"mean={stats['mean']}A median={stats['median']}A stdev={stats['stdev']}A "
            f"min={stats['min']}A max={stats['max']}A"
        )

    comparison = framework.compare_runs(
        results["greenlee"]["test_run_id"],
        results["entes"]["test_run_id"],
    )
    # Keep comparison simple (entes - greenlee) to demonstrate delta API output.
    print("\nCross-meter comparison (ENTES - Greenlee):")
    print(comparison["metric_deltas"])


if __name__ == "__main__":
    main()
