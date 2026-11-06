import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .gui.helper_client import HelperClient  # noqa: E402
from .gui.window import MainWindow  # noqa: E402


def main() -> int:
    helper = HelperClient()
    window = MainWindow(helper)
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    Gtk.main()
    helper.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
