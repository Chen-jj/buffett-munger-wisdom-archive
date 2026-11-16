"""Real filesystem behavior without external binaries; all created files are retained."""

from pathlib import Path

import pytest

from subtitle_rendering.infrastructure.local import LocalRenderingArtifactStore, SystemClock
















def test_system_clock_is_explicit_utc():
    from datetime import datetime
    timestamp = SystemClock().now_utc()
    assert timestamp.endswith("Z")
    assert datetime.fromisoformat(timestamp.replace("Z", "+00:00")).utcoffset().total_seconds() == 0
