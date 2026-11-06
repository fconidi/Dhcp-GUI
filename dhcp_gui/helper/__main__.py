import sys

from .daemon import serve

# Usage: python -m dhcp_gui.helper [none|read|write]  (default: unprivileged "none" only)
# The classes served are fixed by the wrapper that started the process, never by the client.
CLASSES = {"none": {"none"}, "read": {"none", "read"}, "write": {"none", "read", "write"}}
mode = sys.argv[1] if len(sys.argv) > 1 else "none"
if mode not in CLASSES:
    sys.exit("unknown mode")
sys.exit(serve(allowed=CLASSES[mode], once=mode != "none"))
