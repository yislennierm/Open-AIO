from __future__ import annotations

import subprocess
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_URL = "http://127.0.0.1:8000"
CREATE_NO_WINDOW = 0x08000000
EDGE_PATHS = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


def main() -> int:
    url = f"{SERVER_URL}/cam"
    profile_dir = ROOT / "logs" / "cam-edge-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    for edge_path in EDGE_PATHS:
        if edge_path.exists():
            subprocess.Popen(
                [str(edge_path), f"--app={url}", "--new-window", f"--user-data-dir={profile_dir}"],
                cwd=str(ROOT),
                creationflags=CREATE_NO_WINDOW,
                close_fds=True,
            )
            return 0
    webbrowser.open(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
