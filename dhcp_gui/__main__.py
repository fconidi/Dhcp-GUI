import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .i18n import translate  # noqa: E402


def main() -> int:
    window = Gtk.Window(title=translate("app_title"))
    window.set_default_size(720, 480)
    window.add(Gtk.Label(label=translate("app_subtitle")))
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
