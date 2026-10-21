# PyInstaller build recipe. Run through packaging/build.py on each target OS:
# PyInstaller cannot cross-build, so Windows builds on Windows and macOS on macOS.
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
NAME = "NGO Privacy Helper"
VERSION = re.search(r'"(.+)"', (ROOT / "privacy_helper" / "__init__.py").read_text()).group(1)
BUNDLE_ID = "org.startbench.ngoprivacyhelper"

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "privacy_helper" / "resources"), "privacy_helper/resources")],
    # Qt modules the app never uses; keeps the download smaller. (QtNetwork is used: single running copy.)
    excludes=["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtSql",
              "PySide6.QtTest", "PySide6.QtOpenGL", "PySide6.QtDBus", "PySide6.QtConcurrent"],
)
pyz = PYZ(a.pure)

version_info = None
if sys.platform == "win32":
    from PyInstaller.utils.win32 import versioninfo as vi
    nums = tuple(int(n) for n in VERSION.split(".")) + (0,)
    version_info = vi.VSVersionInfo(
        ffi=vi.FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[vi.StringFileInfo([vi.StringTable("040904B0", [
            vi.StringStruct("CompanyName", "Startbench Innovation Hub"),
            vi.StringStruct("FileDescription", NAME),
            vi.StringStruct("FileVersion", VERSION),
            vi.StringStruct("ProductName", NAME),
            vi.StringStruct("ProductVersion", VERSION),
            vi.StringStruct("OriginalFilename", f"{NAME}.exe"),
        ])]), vi.VarFileInfo([vi.VarStruct("Translation", [1033, 1200])])],
    )

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=NAME,
    console=False,                       # no black console window
    icon=str(ROOT / "packaging" / ("icon.icns" if sys.platform == "darwin" else "icon.ico")),
    version=version_info,
    upx=False,                           # UPX breaks macOS signing and triggers antivirus false alarms
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{NAME}.app",
        icon=str(ROOT / "packaging" / "icon.icns"),
        bundle_identifier=BUNDLE_ID,
        version=VERSION,
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "12.0",       # Qt 6.8 minimum
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,  # follow light/dark mode
            "LSApplicationCategoryType": "public.app-category.productivity",
            "NSHumanReadableCopyright": "Free for non-profit organisations. Startbench Innovation Hub.",
            # Double-clicking a .nph file opens it in the app.
            "UTExportedTypeDeclarations": [{
                "UTTypeIdentifier": f"{BUNDLE_ID}.encrypted",
                "UTTypeDescription": "NGO Privacy Helper encrypted file",
                "UTTypeConformsTo": ["public.data"],
                "UTTypeTagSpecification": {"public.filename-extension": ["nph"]},
            }],
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "NGO Privacy Helper encrypted file",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Owner",
                "LSItemContentTypes": [f"{BUNDLE_ID}.encrypted"],
            }],
        },
    )
