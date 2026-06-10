"""Cross-platform launcher: starts the server, opens the browser, cleans up on exit."""

import signal
import subprocess
import sys
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
SERVER_SCRIPT = PROJECT_ROOT / "src" / "server.py"
PORT = 8765


def wait_for_server(timeout: float = 30) -> bool:
    """Block until the server is accepting TCP connections."""
    import socket
    import time
    for _ in range(int(timeout * 2)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        try:
            sock.connect(("127.0.0.1", PORT))
            sock.close()
            return True
        except (ConnectionRefusedError, OSError):
            sock.close()
        time.sleep(0.5)
    return False


def main() -> None:
    # Resolve Python executable: prefer venv, fall back to sys.executable
    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if sys.platform == "win32":
        venv_unix = PROJECT_ROOT / ".venv" / "bin" / "python"
        if venv_python.exists():
            python_exe = str(venv_python)
        elif venv_unix.exists():
            python_exe = str(venv_unix)
        else:
            python_exe = sys.executable
    else:
        venv_unix = PROJECT_ROOT / ".venv" / "bin" / "python"
        if venv_unix.exists():
            python_exe = str(venv_unix)
        else:
            python_exe = sys.executable

    if not Path(python_exe).exists():
        print(f"ERROR: Python not found. Checked: {python_exe}", file=sys.stderr)
        sys.exit(1)

    print(f"Starting transcription server on port {PORT}...")
    server_proc = subprocess.Popen(
        [python_exe, str(SERVER_SCRIPT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Cleanup handler
    def cleanup():
        print("\nShutting down...", file=sys.stderr)
        if server_proc.poll() is None:
            try:
                if sys.platform == "win32":
                    server_proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    server_proc.terminate()
                try:
                    server_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server_proc.kill()
                    server_proc.wait()
            except Exception as e:
                print(f"Cleanup error: {e}", file=sys.stderr)

    # Handle Ctrl+C
    def signal_handler(sig, frame):
        cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Wait for server to be ready
    ready = wait_for_server()
    if ready:
        print("Server ready!")
    else:
        print("Server started (model may still be loading).")

    # Open browser
    url = f"http://127.0.0.1:{PORT}"
    print(f"Opening {url} ...")
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"Could not open browser: {e}", file=sys.stderr)
        print(f"Manually open: {url}", file=sys.stderr)

    print("Press Ctrl+C to stop.\n")

    # Wait for server process (it will exit when heartbeat times out or Ctrl+C)
    try:
        server_proc.wait()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
