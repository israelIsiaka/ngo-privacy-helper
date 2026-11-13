"""Build the installer for the OS this runs on.

    python packaging/build.py

macOS   -> dist/Encryptra-<version>-macOS-<arch>.dmg
Windows -> dist/Encryptra-<version>-Windows-Setup.exe  (needs Inno Setup 6)
"""

import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "Encryptra"
VERSION = re.search(r'"(.+)"', (ROOT / "privacy_helper" / "__init__.py").read_text()).group(1)
DIST = ROOT / "dist"


def run(*cmd) -> None:
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def pyinstaller() -> None:
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", DIST, "--workpath", ROOT / "build", ROOT / "packaging" / "ngo_privacy_helper.spec")


def mac_dmg() -> Path:
    arch = "AppleSilicon" if platform.machine() == "arm64" else "Intel"
    dmg = DIST / f"Encryptra-{VERSION}-macOS-{arch}.dmg"
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / NAME
        stage.mkdir()
        # ditto keeps the bundle's symlinks and signatures intact; cp -r does not.
        run("ditto", DIST / f"{NAME}.app", stage / f"{NAME}.app")
        os.symlink("/Applications", stage / "Applications")   # drag-to-install
        dmg.unlink(missing_ok=True)
        run("hdiutil", "create", "-volname", NAME, "-srcfolder", stage, "-format", "UDZO", "-ov", dmg)
    return dmg


def windows_installer() -> Path:
    iscc = shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if not Path(iscc).exists() and not shutil.which("iscc"):
        sys.exit("Inno Setup 6 is needed: https://jrsoftware.org/isdl.php")
    run(iscc, f"/DAppVersion={VERSION}", f"/DSourceDir={DIST / NAME}", f"/DOutputDir={DIST}",
        ROOT / "packaging" / "windows" / "installer.iss")
    return DIST / f"Encryptra-{VERSION}-Windows-Setup.exe"


def main() -> None:
    pyinstaller()
    if sys.platform == "darwin":
        out = mac_dmg()
    elif sys.platform == "win32":
        out = windows_installer()
    else:
        out = DIST / NAME
    print(f"\nBuilt {out}")


if __name__ == "__main__":
    main()
