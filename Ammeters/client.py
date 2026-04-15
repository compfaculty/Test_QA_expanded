from socket import socket, AF_INET, SOCK_STREAM


def request_current_from_ammeter(port: int, command: bytes, timeout_seconds: float = 3.0) -> float:
    with socket(AF_INET, SOCK_STREAM) as s:
        # timeout prevents indefinite hangs when emulator threads are not available.
        s.settimeout(timeout_seconds)
        s.connect(("localhost", port))
        s.sendall(command)
        data = s.recv(1024)
        if not data:
            raise RuntimeError(f"No data received from port {port}.")

        try:
            decoded = data.decode("utf-8").strip()
        except UnicodeDecodeError as decode_error:
            raise RuntimeError(f"Received non-UTF8 response from port {port}.") from decode_error
        if decoded.startswith("ERROR:"):
            # server protocol errors are raised directly to keep failures explicit for tests.
            raise RuntimeError(decoded)

        # parse to float here so all callers get a typed measurement.
        try:
            measurement = float(decoded)
        except ValueError as parse_error:
            raise RuntimeError(f"Received non-numeric measurement from port {port}: '{decoded}'") from parse_error
        print(f"Received current measurement from port {port}: {measurement} A")
        return measurement
