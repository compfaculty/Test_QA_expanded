import socket
import time
import random
import errno
from abc import ABC, abstractmethod

NotImplementedErrorMsg = "Subclasses must implement this property."


class AmmeterEmulatorBase(ABC):
    def __init__(self, port: int):
        """Initialize emulator instance with its listening TCP port."""
        self.port = port
        random.seed(time.time())  # seed the random number generator for each instance

    def start_server(self):
        """
        Starts the server to listen for client requests.
        The server will run indefinitely, handling one client request at a time.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("localhost", self.port))
            except OSError as bind_error:
                # surface a clear failure when another process already occupies this emulator port.
                address_in_use_errors = {errno.EADDRINUSE, 10048}  # Linux/macOS + Windows WSAEADDRINUSE
                if bind_error.errno in address_in_use_errors or getattr(bind_error, "winerror", None) == 10048:
                    raise RuntimeError(
                        f"{self.__class__.__name__} could not start on port {self.port}: "
                        "address already in use. Stop the conflicting process or change the configured port."
                    ) from bind_error
                raise RuntimeError(
                    f"{self.__class__.__name__} failed to bind on port {self.port}: {bind_error}"
                ) from bind_error
            s.listen()
            print(f"{self.__class__.__name__} is running on port {self.port}")
            while True:
                conn, addr = s.accept()
                with conn:
                    print(f"Connected by {addr}")
                    data = self._receive_command(conn)
                    if self.is_valid_command(data):
                        # Call the specific measure_current() method defined in subclasses
                        current = self.measure_current()
                        conn.sendall(str(current).encode("utf-8"))
                    else:
                        # explicit protocol error response helps client-side diagnostics.
                        conn.sendall(
                            f"ERROR: Unsupported command for {self.__class__.__name__}".encode("utf-8")
                        )

    @property
    @abstractmethod
    def get_current_command(self) -> bytes:
        """
        This property must be implemented by each subclass to provide the specific
        command to get the current measurement.
        """
        raise NotImplementedError(NotImplementedErrorMsg)

    def is_valid_command(self, command: bytes) -> bool:
        """Validate that the received command matches this emulator protocol."""
        return command == self.get_current_command

    def _receive_command(self, conn: socket.socket, timeout_seconds: float = 1.0) -> bytes:
        """Read command bytes from socket with timeout and size bounds."""
        expected_command = self.get_current_command
        max_bytes = max(len(expected_command) * 2, 1024)
        received = bytearray()
        conn.settimeout(timeout_seconds)

        while len(received) < max_bytes:
            try:
                chunk = conn.recv(256)
            except socket.timeout:
                # timeout ends reads for fragmented/incomplete commands instead of blocking forever.
                break

            if not chunk:
                break

            received.extend(chunk)
            if len(received) >= len(expected_command):
                # stop once enough bytes arrived to validate command equality.
                break

        return bytes(received)

    @abstractmethod
    def measure_current(self) -> float:
        """
        This method must be implemented by each subclass to provide the specific
        logic for current measurement.
        """
        raise NotImplementedError(NotImplementedErrorMsg)
