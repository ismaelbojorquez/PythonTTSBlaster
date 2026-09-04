"""Compile official PJSIP 2.17 into the current Python environment (Linux/macOS).

Run inside the virtualenv after installing setuptools, wheel, and swig.
The source and build output stay in build/. No system installation or sudo.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

VERSION = "2.17"
ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"


def main() -> None:
    if sys.prefix == sys.base_prefix:
        raise SystemExit("Ejecuta este script con .venv/bin/python")
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    if sys.platform == "darwin":
        # python.org universal2 Python otherwise tries linking x86_64 against arm64 libs.
        env["ARCHFLAGS"] = f"-arch {platform.machine()}"
    for command in ("make", "swig", "cc", "c++"):
        if not shutil.which(command, path=env["PATH"]):
            raise SystemExit(
                f"Falta {command}; consulta las dependencias de compilación en README.md"
            )
    BUILD.mkdir(exist_ok=True)
    archive = BUILD / f"pjproject-{VERSION}.tar.gz"
    source = BUILD / f"pjproject-{VERSION}"
    if not archive.exists():
        url = f"https://codeload.github.com/pjsip/pjproject/tar.gz/refs/tags/{VERSION}"
        print(f"Descargando PJSIP {VERSION} desde su repositorio oficial", flush=True)
        temporary = archive.with_suffix(".download")
        urllib.request.urlretrieve(url, temporary)
        temporary.replace(archive)
    if not source.exists():
        with tarfile.open(archive) as tar:
            tar.extractall(BUILD, filter="data")
    (source / "pjlib/include/pj/config_site.h").write_text(
        "#define PJSUA_MAX_CALLS 64\n"
        "#define PJSIP_MAX_TSX_COUNT 1023\n"
        "#define PJSIP_MAX_DIALOG_COUNT 1023\n"
    )

    def run(args, cwd=source):
        subprocess.run(args, cwd=cwd, env=env, check=True)

    run(
        [
            "./configure",
            "CFLAGS=-fPIC",
            "CXXFLAGS=-fPIC",
            "--disable-sound",
            "--disable-video",
            "--disable-ssl",
            "--disable-libyuv",
            "--disable-ffmpeg",
            "--disable-v4l2",
            "--disable-openh264",
            "--disable-vpx",
        ]
    )
    run(["make", "dep"])
    run(["make", f"-j{min(8, os.cpu_count() or 2)}"])
    bindings = source / "pjsip-apps/src/swig/python"
    run(["make", f"PYTHON_EXE={sys.executable}"], cwd=bindings)
    run([sys.executable, "-m", "pip", "install", "--no-build-isolation", str(bindings)])
    run([sys.executable, "-c", "import pjsua2; print('PJSUA2 instalado correctamente')"])


if __name__ == "__main__":
    main()
