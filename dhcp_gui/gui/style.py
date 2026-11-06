"""Content styling. The window frame and the base colors come from the system theme;
everything here is derived from the theme's own colors so light and dark both work."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

CSS = """
@define-color dg_accent #2a76c6;
@define-color dg_accent_hi #3b8ae0;
@define-color dg_ok #2f9e63;
@define-color dg_warn #d08a1c;
@define-color dg_err #d04a3a;

.dg-root { padding: 0; }

/* top status band */
.dg-band {
  padding: 14px 18px;
  background-image: linear-gradient(to bottom,
      alpha(@dg_accent, 0.14), alpha(@dg_accent, 0.05));
  border-bottom: 1px solid alpha(@theme_fg_color, 0.14);
}
.dg-band-title { font-size: 1.25em; font-weight: 700; }
.dg-band-detail { opacity: 0.72; }
.dg-dot { min-width: 12px; min-height: 12px; border-radius: 6px;
  background-color: alpha(@theme_fg_color, 0.4); }
.dg-dot.running { background-color: @dg_ok; box-shadow: 0 0 0 4px alpha(@dg_ok, 0.22); }
.dg-dot.stopped { background-color: alpha(@theme_fg_color, 0.45); }
.dg-dot.problem { background-color: @dg_warn; box-shadow: 0 0 0 4px alpha(@dg_warn, 0.22); }

/* banners and message bar */
.dg-banner {
  padding: 9px 14px; margin: 10px 18px 0 18px; border-radius: 6px;
  background-color: alpha(@dg_warn, 0.16);
  border: 1px solid alpha(@dg_warn, 0.55);
}
.dg-banner.info { background-color: alpha(@dg_accent, 0.13); border-color: alpha(@dg_accent, 0.5); }
.dg-msg {
  padding: 9px 14px; margin: 0 18px 12px 18px; border-radius: 6px;
  border: 1px solid alpha(@theme_fg_color, 0.2);
}
.dg-msg.ok { background-color: alpha(@dg_ok, 0.16); border-color: alpha(@dg_ok, 0.6); }
.dg-msg.error { background-color: alpha(@dg_err, 0.15); border-color: alpha(@dg_err, 0.6); }

/* tabs */
notebook.dg-tabs > header { background-color: transparent; padding: 0 12px; }
notebook.dg-tabs > header > tabs > tab {
  padding: 9px 16px; min-height: 0; border-radius: 6px 6px 0 0; opacity: 0.8;
  transition: background-color 150ms ease-out, opacity 150ms ease-out;
}
notebook.dg-tabs > header > tabs > tab:checked { opacity: 1; font-weight: 600;
  box-shadow: inset 0 -2px @dg_accent; }
notebook.dg-tabs > header > tabs > tab:hover:not(:checked) { background-color: alpha(@theme_fg_color, 0.07); }
notebook.dg-tabs > stack { background-color: transparent; }

/* sections and form */
.dg-section-title { font-weight: 700; font-size: 1.05em; }
.dg-section { padding: 14px 16px; border-radius: 8px;
  background-color: alpha(@theme_fg_color, 0.04);
  border: 1px solid alpha(@theme_fg_color, 0.12); }
.dg-label { opacity: 0.85; }
.dg-hint { opacity: 0.68; font-size: 0.9em; }
entry.dg-field, combobox.dg-field entry { min-height: 28px; }
entry.dg-field:focus, combobox.dg-field entry:focus {
  border-color: @dg_accent; box-shadow: 0 0 0 2px alpha(@dg_accent, 0.35); }
entry.dg-field.error, combobox.dg-field.error entry {
  border-color: @dg_err; box-shadow: 0 0 0 2px alpha(@dg_err, 0.3); }

/* buttons */
button.dg-primary { background-image: none; background-color: @dg_accent; color: #ffffff;
  border-color: shade(@dg_accent, 0.82); font-weight: 600; padding: 7px 18px; text-shadow: none; }
button.dg-primary:hover { background-color: @dg_accent_hi; }
button.dg-primary:disabled { background-color: alpha(@dg_accent, 0.4); color: alpha(#ffffff, 0.85); }
button.dg-danger { color: mix(@theme_fg_color, @dg_err, 0.65); }
button.dg-quiet { background-image: none; background-color: transparent; border-color: transparent;
  color: @dg_accent_hi; box-shadow: none; }
button.dg-quiet:hover { background-color: alpha(@dg_accent, 0.15); }
button { transition: background-color 150ms ease-out, border-color 150ms ease-out; }
button:focus { outline-color: alpha(@dg_accent, 0.7); outline-offset: 1px; outline-style: solid; outline-width: 2px; }

/* NIC rows and badges */
.dg-row { padding: 10px 14px; border-bottom: 1px solid alpha(@theme_fg_color, 0.1); }
.dg-nic-name { font-weight: 700; }
.dg-mono { font-family: monospace; }
.dg-badge { padding: 1px 9px; border-radius: 10px; font-size: 0.88em;
  border: 1px solid alpha(@theme_fg_color, 0.3); }
.dg-badge.ok { background-color: alpha(@dg_ok, 0.18); border-color: alpha(@dg_ok, 0.6);
  color: mix(@theme_fg_color, @dg_ok, 0.45); }
.dg-badge.warn { background-color: alpha(@dg_warn, 0.2); border-color: alpha(@dg_warn, 0.65);
  color: mix(@theme_fg_color, @dg_warn, 0.45); }
.dg-badge.muted { opacity: 0.75; }

/* usage bars */
levelbar.dg-usage block.filled { background-color: @dg_accent; border-radius: 4px; }
levelbar.dg-usage.high block.filled { background-color: @dg_warn; }
levelbar.dg-usage.full block.filled { background-color: @dg_err; }
levelbar.dg-usage block.empty { background-color: alpha(@theme_fg_color, 0.14); border-radius: 4px; }
levelbar.dg-usage trough { min-height: 10px; }

.dg-actionbar { padding: 10px 18px; border-top: 1px solid alpha(@theme_fg_color, 0.14);
  background-color: alpha(@theme_fg_color, 0.04); }
.dg-empty { padding: 28px; opacity: 0.75; }
treeview.dg-list { background-color: transparent; }
treeview.dg-list:selected { background-color: alpha(@dg_accent, 0.55); color: @theme_selected_fg_color; }
"""

_installed = False


def install():
    global _installed
    if _installed:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS.encode())
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _installed = True
