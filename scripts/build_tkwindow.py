"""Build script: package src/tkwindow.py into a standalone Linux binary."""

import argparse
import os
import shutil
import subprocess
import sys
import sysconfig

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
BUILD_DIR = os.path.join(PROJECT_DIR, "dist")


def find_python_lib() -> str:
    """Return the site-packages directory for the current Python."""
    return sysconfig.get_paths()["purelib"]


def build_pyinstaller(spec_path: str, dist_name: str) -> None:
    """Run PyInstaller with the given spec file."""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        "--distpath", BUILD_DIR,
        "--workpath", os.path.join(PROJECT_DIR, ".build"),
        spec_path,
    ]
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=PROJECT_DIR)


def create_spec(dist_name: str) -> str:
    """Create a PyInstaller spec file for tkwindow.py."""
    site_packages = find_python_lib()
    spec_content = (
        "# -*- mode: python ; coding: utf-8 -*-\n"
        "\n"
        "block_cipher = None\n"
        "\n"
        "a = Analysis(\n"
        "    ['src/tkwindow.py'],\n"
        "    pathex=[],\n"
        "    binaries=[\n"
        "        ('.venv/lib/python3.14/site-packages/vosk/libvosk.so', 'vosk'),\n"
        "    ],\n"
        "    datas=[\n"
        "        ('resources/bavardage.png', 'resources'),\n"
        "    ],\n"
        "    hiddenimports=[\n"
        "        'vosk',\n"
        "        'numpy',\n"
        "        'loguru',\n"
        "        'ttkbootstrap',\n"
        "        'ttkbootstrap.style',\n"
        "        'PIL',\n"
        "        'PIL._tkinter_finder',\n"
        "        'tkinter',\n"
        "        'tkinter.font',\n"
        "        'tkinter.messagebox',\n"
        "    ],\n"
        "    hookspath=[],\n"
        "    hooksconfig={},\n"
        "    runtime_hooks=[],\n"
        "    excludes=[\n"
        "        'PyQt5',\n"
        "        'PyQt6',\n"
        "        'PySide2',\n"
        "        'PySide6',\n"
        "        'setuptools',\n"
        "        'unittest',\n"
        "        'xml.etree',\n"
        "    ],\n"
        "    win_no_prefer_redirects=False,\n"
        "    win_private_assemblies=False,\n"
        "    cipher=block_cipher,\n"
        "    noarchive=True,\n"
        ")\n"
        "\n"
        "pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)\n"
        "\n"
        "exe = EXE(\n"
        "    pyz,\n"
        "    a.scripts,\n"
        "    a.binaries,\n"
        "    a.zipfiles,\n"
        "    a.datas,\n"
        "    [],\n"
        f"    name='{dist_name}',\n"
        "    debug=False,\n"
        "    bootloader_ignore_signals=False,\n"
        "    strip=False,\n"
        "    upx=True,\n"
        "    upx_exclude=[],\n"
        "    runtime_tmpdir=None,\n"
        "    console=False,\n"
        "    disable_windowed_traceback=False,\n"
        "    argv_emulation=False,\n"
        "    target_arch=None,\n"
        "    codesign_identity=None,\n"
        "    entitlements_file=None,\n"
        ")\n"
    )
    spec_path = os.path.join(PROJECT_DIR, "tkwindow.spec")
    with open(spec_path, "w") as f:
        f.write(spec_content)
    return spec_path


def generate_desktop_file(dist_dir: str, dist_name: str) -> None:
    """Generate a .desktop file and copy the icon to dist."""
    desktop_content = (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        f"Name=Bavardage\n"
        "Comment=Real-time French speech transcription\n"
        f"Exec=~/.local/bin/{dist_name}\n"
        "Icon=~/.local/bin/bavardage.png\n"
        "Terminal=false\n"
        "Type=Application\n"
        "Categories=AudioVideo;Audio;Accessibility;\n"
    )
    desktop_path = os.path.join(dist_dir, f"{dist_name}.desktop")
    with open(desktop_path, "w") as f:
        f.write(desktop_content)
    print(f"Desktop file created: {desktop_path}")

    # Copy icon to dist
    icon_src = os.path.join(PROJECT_DIR, "resources", "bavardage.png")
    icon_dst = os.path.join(dist_dir, "bavardage.png")
    shutil.copy2(icon_src, icon_dst)
    print(f"Icon copied: {icon_dst}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build standalone tkwindow binary")
    parser.add_argument("--clean", action="store_true", help="Remove build/dist directories first")
    args = parser.parse_args()

    if args.clean:
        for d in [BUILD_DIR, os.path.join(PROJECT_DIR, ".build")]:
            if os.path.exists(d):
                shutil.rmtree(d)

    # Check PyInstaller is installed
    try:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--version"],
                       check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("PyInstaller not found. Install it with: pip install PyInstaller")
        sys.exit(1)

    spec_path = create_spec("bavardage")
    print(f"Spec file created: {spec_path}")
    build_pyinstaller(spec_path, "bavardage")
    print(f"\nBinary built successfully: {os.path.join(BUILD_DIR, 'bavardage')}")

    # Generate .desktop file and copy icon
    generate_desktop_file(BUILD_DIR, "bavardage")


if __name__ == "__main__":
    main()
