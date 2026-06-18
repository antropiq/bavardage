"""Bootstrap entry point for PyInstaller one-file build.

Uses absolute imports so the bundled binary works outside the project.
"""

from src.tkwindow.cli import main

main()
