import os
from pathlib import Path


CHANNEL = os.environ.get("TONGJI_BROWSER") or "chrome"
if CHANNEL not in {"chrome", "chromium"}:
    raise SystemExit("TONGJI_BROWSER 支持 chrome 或 chromium")
PROFILE = Path.home() / ".local" / "share" / "tongji-cli" / CHANNEL


def open_session(engine, profile, *, interactive=False, no_viewport=False):
    return engine.chromium.launch_persistent_context(
        profile, channel=CHANNEL, headless=not interactive, no_viewport=no_viewport,
        args=["--restore-last-session"], ignore_default_args=["about:blank"],
    )
