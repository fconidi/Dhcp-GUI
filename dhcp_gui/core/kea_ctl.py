"""Client for the Kea control socket (one command per connection)."""
from __future__ import annotations

import json
import socket

SOCKET_PATH = "/run/kea/kea4-ctrl-socket"
MAX_ANSWER = 4 * 1024 * 1024


def send(command, arguments=None, path=SOCKET_PATH, timeout=5):
    """Return the Kea answer list, or None when the socket is unavailable."""
    body = {"command": command}
    if arguments:
        body["arguments"] = arguments
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(path)
            sock.sendall(json.dumps(body).encode())
            data = b""
            while len(data) < MAX_ANSWER:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
                try:
                    answer = json.loads(data)
                    break
                except ValueError:
                    continue
            else:
                return None
            answer = json.loads(data)
    except (OSError, ValueError):
        return None
    return answer if isinstance(answer, list) else [answer]
