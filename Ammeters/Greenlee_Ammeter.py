from Ammeters.base_ammeter import AmmeterEmulatorBase
from src.utils.Utils import generate_random_float


class GreenleeAmmeter(AmmeterEmulatorBase):
    @property
    def get_current_command(self) -> bytes:
        """Return the protocol command accepted by the Greenlee emulator."""
        return b"MEASURE_GREENLEE -get_measurement"

    def measure_current(self) -> float:
        """Compute current using a simple V/R model with random inputs."""
        voltage = generate_random_float(1.0, 10.0)  # Random voltage (1V - 10V)
        resistance = generate_random_float(0.1, 100.0)  # Random resistance (0.1 Ohm - 100 Ohm)
        current = voltage / resistance
        # keep console output ASCII-safe
        print(f"Greenlee Ammeter - Voltage: {voltage}V, Resistance: {resistance} Ohm, Current: {current}A")
        return current
