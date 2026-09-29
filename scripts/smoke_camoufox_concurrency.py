"""Launch real Camoufox profiles concurrently and verify basic isolation.

This is intentionally a headful smoke test: it exercises the same native-window
path as the Manager UI. The temporary profiles are removed after every run.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.browser_manager import BrowserManager  # noqa: E402
from backend.runtime import RuntimeConfig  # noqa: E402


def _profile(root: Path, index: int) -> dict[str, object]:
    return {
        "id": f"smoke-{index}",
        "name": f"Camoufox smoke {index}",
        "fingerprint_seed": 10000 + index,
        "user_data_dir": str(root / f"profile-{index}"),
        "screen_width": 1280,
        "screen_height": 800,
        "capture_preview": False,
        "restore_session": False,
        "allow_3p_cookies": True,
        "geoip": False,
    }


async def _run(sessions: int, hold_seconds: float) -> None:
    with tempfile.TemporaryDirectory(prefix="cloakbrowser-camoufox-smoke-") as temp:
        root = Path(temp)
        runtime = RuntimeConfig(
            host_os="windows",
            runtime_mode="native",
            viewer_mode="native-window",
            data_dir=root,
        )
        manager = BrowserManager(runtime_config=runtime, engine_name="camoufox")
        manager.resolve_binary_status()
        profiles = [_profile(root, index) for index in range(1, sessions + 1)]

        try:
            running = await asyncio.gather(
                *(manager.launch(profile) for profile in profiles)
            )

            profile_dirs = {
                str(item.user_data_dir.resolve())
                for item in running
                if item.user_data_dir is not None
            }
            if len(profile_dirs) != sessions:
                raise AssertionError("Concurrent sessions did not receive unique directories")

            origin = "https://profile-isolation.invalid"
            for index, item in enumerate(running, start=1):
                await item.context.add_cookies(
                    [
                        {
                            "name": "profile_marker",
                            "value": str(index),
                            "url": origin,
                        }
                    ]
                )

            for index, item in enumerate(running, start=1):
                cookies = await item.context.cookies(origin)
                markers = [
                    cookie["value"]
                    for cookie in cookies
                    if cookie["name"] == "profile_marker"
                ]
                if markers != [str(index)]:
                    raise AssertionError(
                        f"Profile {index} saw unexpected marker cookies: {markers}"
                    )

            try:
                await manager.launch(profiles[0])
            except RuntimeError as exc:
                if "already running" not in str(exc):
                    raise
            else:
                raise AssertionError("A second launch of the same profile was accepted")

            print(
                f"PASS: {sessions} concurrent Camoufox sessions, "
                "unique profile directories, isolated cookies, duplicate launch blocked"
            )
            if hold_seconds > 0:
                await asyncio.sleep(hold_seconds)
        finally:
            await asyncio.gather(
                *(manager.stop(str(profile["id"])) for profile in profiles),
                return_exceptions=True,
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=3)
    parser.add_argument("--hold-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if not 2 <= args.sessions <= 10:
        parser.error("--sessions must be between 2 and 10")
    asyncio.run(_run(args.sessions, args.hold_seconds))


if __name__ == "__main__":
    main()
