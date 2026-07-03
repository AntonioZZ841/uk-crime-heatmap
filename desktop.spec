# PyInstaller spec for the desktop build (onedir: instant start, no temp
# extraction of the 400MB database on every launch). Run from the repo root:
#   pyinstaller desktop.spec
# Expects data/crime.duckdb to exist (run the pipeline first).
import sys

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]
if sys.platform in ("win32", "darwin"):
    hiddenimports.append("webview")  # GUI path; hooks pull in WebView2 / WKWebView glue

a = Analysis(
    ["desktop.py"],
    pathex=[],
    datas=[
        ("frontend", "frontend"),
        ("data/crime.duckdb", "data"),
    ],
    hiddenimports=hiddenimports,
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="uk-crime-heatmap",
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="uk-crime-heatmap",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="UK Crime Heatmap.app",
        bundle_identifier="uk.crime-heatmap.desktop",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )
