#!/usr/bin/python3
"""Build the dhcp-gui Debian package from an explicit file list."""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

MODULES = (
    "__init__.py", "__main__.py", "i18n.py",
    "core/__init__.py", "core/apply.py", "core/inventory.py", "core/kea_ctl.py", "core/kea_import.py",
    "core/model.py", "core/paths.py", "core/protocol.py", "core/service.py", "core/suggest.py",
    "gui/__init__.py", "gui/formlogic.py", "gui/helper_client.py", "gui/window.py",
    "helper/__init__.py", "helper/__main__.py", "helper/daemon.py",
)
LIB = "usr/lib/dhcp-gui"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build Dhcp-GUI for Debian")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parent
    package = source / "dhcp_gui"
    match = re.search(r'__version__ = "([^"]+)"', (package / "__init__.py").read_text(encoding="utf-8"))
    if match is None:
        raise ValueError("package version is missing")
    version = match.group(1)
    with tempfile.TemporaryDirectory(prefix="package-", dir=output) as tmp:
        root = Path(tmp)

        def install(origin: Path, relative: str, executable: bool = False):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin, target)
            target.chmod(0o755 if executable else 0o644)

        for name in MODULES:
            install(package / name, f"{LIB}/dhcp_gui/{name}")
        install(source / "packaging/dhcp-gui", "usr/bin/dhcp-gui", True)
        for mode in ("read", "write"):
            install(source / f"packaging/dhcp-gui-helper-{mode}", f"{LIB}/dhcp-gui-helper-{mode}", True)
        install(source / "packaging/com.syslinuxos.dhcp-gui.policy",
                "usr/share/polkit-1/actions/com.syslinuxos.dhcp-gui.policy")
        install(source / "packaging/dhcp-gui.desktop", "usr/share/applications/dhcp-gui.desktop")
        install(source / "packaging/dhcp-gui.menu", "etc/xdg/menus/applications-merged/dhcp-gui.menu")
        install(source / "data/dhcp-gui.svg", "usr/share/icons/hicolor/scalable/apps/dhcp-gui.svg")
        for name in ("README.md", "CHANGELOG.md", "LICENSE"):
            install(source / name, f"usr/share/doc/dhcp-gui/{name}")
        control = root / "DEBIAN"
        control.mkdir()
        text = (source / "packaging/control").read_text(encoding="utf-8").replace("@VERSION@", version)
        (control / "control").write_text(text, encoding="utf-8")
        root.chmod(0o755)
        for directory in root.rglob("*"):
            if directory.is_dir():
                directory.chmod(0o755)
        artifact = output / f"dhcp-gui_{version}_all.deb"
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(root), str(artifact)], check=True)
        print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
