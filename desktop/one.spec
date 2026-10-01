from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent
a = Analysis([str(root / "desktop/backend_entry.py")], pathex=[str(root / "src")],
             binaries=[], datas=collect_data_files("nebula_one"),
             hiddenimports=collect_submodules("nebula_one") + collect_submodules("uvicorn"),
             hookspath=[], runtime_hooks=[], excludes=["pytest", "tkinter"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="nebula-one-api",
          console=True, debug=False, strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="nebula-one-api", strip=False, upx=False)
