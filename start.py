"""Cross-platform launcher: starts the server and cleans up on exit."""

import os
import signal
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
SERVER_SCRIPT = PROJECT_ROOT / "src" / "server.py"
PORT = 8765


def get_local_ip() -> str:
    """Get the machine's local LAN IP address."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


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


def _find_python() -> str:
    """Resolve Python executable: prefer venv, fall back to sys.executable."""
    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if sys.platform == "win32":
        venv_unix = PROJECT_ROOT / ".venv" / "bin" / "python"
        if venv_python.exists():
            return str(venv_python)
        elif venv_unix.exists():
            return str(venv_unix)
    else:
        venv_unix = PROJECT_ROOT / ".venv" / "bin" / "python"
        if venv_unix.exists():
            return str(venv_unix)
    return sys.executable


def main() -> None:
    # If --help is requested, delegate to the server directly (no subprocess)
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        subprocess.run([_find_python(), str(SERVER_SCRIPT), "--help"], env=env)
        sys.exit(0)

    # If --console is requested, run console mode directly (no server)
    if "--console" in sys.argv[1:]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        try:
            subprocess.run([_find_python(), str(SERVER_SCRIPT)] + sys.argv[1:], env=env, cwd=str(PROJECT_ROOT))
        except KeyboardInterrupt:
            pass
        sys.exit(0)

    # Parse --ssl flag if present
    use_ssl = "--ssl" in sys.argv[1:]
    scheme = "https" if use_ssl else "http"

    python_exe = _find_python()

    if not Path(python_exe).exists():
        print(f"ERROR: Python not found. Checked: {python_exe}", file=sys.stderr)
        sys.exit(1)

    print(f"Starting transcription server on port {PORT}...")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    server_proc = subprocess.Popen(
        [python_exe, str(SERVER_SCRIPT)] + sys.argv[1:],
        env=env,
        cwd=str(PROJECT_ROOT),
    )

    # Cleanup handler
    def cleanup():
        print("\nShutting down...", file=sys.stderr)
        if server_proc.poll() is None:
            try:
                server_proc.terminate()
                try:
                    server_proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    server_proc.kill()
                    server_proc.communicate()
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
    local_ip = get_local_ip()
    url = f"{scheme}://{local_ip}:{PORT}"
    if ready:
        print(f"Server ready at {url}")
    else:
        print(f"Server started (model may still be loading) at {url}")
    print(f"Also available at {scheme}://127.0.0.1:{PORT}\n")

    print("Press Ctrl+C to stop.\n")

    # Wait for server process (it will exit when Ctrl+C is received)
    try:
        server_proc.communicate()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
