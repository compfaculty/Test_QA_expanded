import threading
import time
from typing import Dict, List, Tuple

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter
from src.utils.config import load_config

EMULATOR_CLASS_MAP: Dict[str, type] = {
    "greenlee": GreenleeAmmeter,
    "entes": EntesAmmeter,
    "circutor": CircutorAmmeter,
}


def _configured_servers() -> List[Tuple[str, int, bytes, type]]:
    config = load_config("config/config.yaml")
    servers: List[Tuple[str, int, bytes, type]] = []
    for ammeter_name, ammeter_config in config.get("ammeters", {}).items():
        ammeter_key = str(ammeter_name).strip().lower()
        ammeter_class = EMULATOR_CLASS_MAP.get(ammeter_key)
        if ammeter_class is None:
            continue
        port = int(ammeter_config["port"])
        command = str(ammeter_config["command"]).encode("utf-8")
        servers.append((ammeter_key, port, command, ammeter_class))
    return servers


def run_emulator(ammeter_class: type, port: int):
    emulator = ammeter_class(port)
    emulator.start_server()


if __name__ == "__main__":
    ammeter_servers = _configured_servers()
    for _, port, _, ammeter_class in ammeter_servers:
        threading.Thread(
            target=run_emulator, args=(ammeter_class, port), daemon=True
        ).start()

    time.sleep(1.5)

    for ammeter_name, port, command, _ in ammeter_servers:
        current_value = request_current_from_ammeter(port, command)
        print(f"{ammeter_name} current value: {current_value} A")
