# SPDX-License-Identifier: AGPL-3.0-only
"""Build a native desktop bundle on the current operating system."""

from __future__ import annotations

import io
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE_FILES = [
    ROOT / "LICENSE", ROOT / "README.md", ROOT / "requirements.txt",
    ROOT / "build.py", ROOT / "run_app.py", ROOT / ".github" / "workflows" / "build.yml",
    ROOT / "assets" / "icon.png",
    *sorted((ROOT / "assets" / "fonts").glob("*")),
    *sorted(path for path in (ROOT / "docs").rglob("*") if path.is_file()),
    *sorted((ROOT / "conversor").glob("*.py")),
    *sorted((ROOT / "tests").glob("*.py")),
    *sorted((ROOT / "resources" / "tessdata").glob("*")),
]


def build() -> Path:
    system = platform.system()
    machine = platform.machine().lower().replace("aarch64", "arm64").replace("amd64", "x64").replace("x86_64", "x64")
    label = {"Linux": "linux", "Windows": "windows", "Darwin": "macos"}.get(system)
    if not label:
        raise SystemExit(f"Unsupported operating system: {system}")

    mode = "--onedir" if system == "Darwin" else "--onefile"
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        mode, "--windowed", "--name", "ConversorEPUB",
        "--icon", str(ROOT / "assets" / "icon.png"),
        "--add-data", f"{ROOT / 'assets' / 'icon.png'}{':' if system != 'Windows' else ';'}assets",
        "--add-data", f"{ROOT / 'assets' / 'fonts'}{':' if system != 'Windows' else ';'}assets/fonts",
        "--add-data", f"{ROOT / 'resources' / 'tessdata'}{':' if system != 'Windows' else ';'}resources/tessdata",
        str(ROOT / "run_app.py"),
    ], cwd=ROOT, check=True)

    executable = ROOT / "dist" / ("ConversorEPUB.app" if system == "Darwin" else "ConversorEPUB.exe" if system == "Windows" else "ConversorEPUB")
    if not executable.exists():
        raise SystemExit(f"Build output missing: {executable}")
    release = ROOT / "release" / f"ConversorEPUB-{label}-{machine}.zip"
    release.parent.mkdir(exist_ok=True)

    source_buffer = io.BytesIO()
    with zipfile.ZipFile(source_buffer, "w", zipfile.ZIP_DEFLATED) as source_zip:
        for file in SOURCE_FILES:
            source_zip.write(file, file.relative_to(ROOT))
    if system == "Darwin":
        # ditto preserves the symlinks and bundle metadata inside a macOS .app.
        staging = ROOT / "release" / "staging"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        shutil.copytree(executable, staging / executable.name, symlinks=True)
        shutil.copy2(ROOT / "LICENSE", staging / "LICENSE")
        shutil.copy2(ROOT / "README.md", staging / "README.md")
        (staging / "codigo-fonte.zip").write_bytes(source_buffer.getvalue())
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", str(staging), str(release)], check=True)
        shutil.rmtree(staging)
    else:
        with zipfile.ZipFile(release, "w", zipfile.ZIP_DEFLATED) as package:
            package.write(executable, executable.name)
            package.write(ROOT / "LICENSE", "LICENSE")
            package.write(ROOT / "README.md", "README.md")
            package.writestr("codigo-fonte.zip", source_buffer.getvalue())
    print(release)
    return release


if __name__ == "__main__":
    build()
