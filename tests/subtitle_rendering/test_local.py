"""Real filesystem behavior without external binaries; all created files are retained."""

from pathlib import Path

import pytest

from subtitle_rendering.infrastructure.local import LocalRenderingArtifactStore, SystemClock


def test_staging_planning_has_no_writes_and_paths_are_unique(tmp_path):
    store = LocalRenderingArtifactStore()
    first, second = store.plan_staging(str(tmp_path)), store.plan_staging(str(tmp_path))
    assert first != second
    assert not tuple(tmp_path.iterdir())
    assert Path(first).parent == tmp_path
    store.create_staging(first)
    assert Path(first).stat().st_dev == tmp_path.stat().st_dev
    assert not (Path(first) / "video_中文字幕.mp4").exists()


def test_exclusive_stage_readback_and_atomic_publish(tmp_path):
    store = LocalRenderingArtifactStore()
    staging = store.plan_staging(str(tmp_path))
    store.create_staging(staging)
    staged, target = str(Path(staging) / "bilingual.ass"), str(tmp_path / "bilingual.ass")
    store.stage_bytes(staged, b"canonical ASS\n")
    assert store.read_bytes(staged) == b"canonical ASS\n"
    assert store.size(staged) == len(b"canonical ASS\n")
    assert len(store.sha256(staged)) == 64
    with pytest.raises(FileExistsError):
        store.stage_bytes(staged, b"cannot replace residual")
    store.publish(staged, target, overwrite=False)
    assert Path(target).read_bytes() == b"canonical ASS\n"
    assert Path(staging).is_dir()


def test_conflict_and_explicit_overwrite_do_not_change_link_target(tmp_path):
    store = LocalRenderingArtifactStore()
    upstream = tmp_path / "upstream.json"
    upstream.write_bytes(b"immutable upstream")
    target = tmp_path / "subtitle_rendering_plan.json"
    target.symlink_to(upstream)
    staging = Path(store.plan_staging(str(tmp_path)))
    store.create_staging(str(staging))
    source = staging / target.name
    store.stage_bytes(str(source), b"new rendering plan")
    with pytest.raises(FileExistsError):
        store.publish(str(source), str(target), overwrite=False)
    assert source.read_bytes() == b"new rendering plan"
    store.publish(str(source), str(target), overwrite=True)
    assert not target.is_symlink() and target.read_bytes() == b"new rendering plan"
    assert upstream.read_bytes() == b"immutable upstream"


def test_dangling_symlink_counts_as_occupied(tmp_path):
    path = tmp_path / "bilingual.ass"
    path.symlink_to(tmp_path / "missing")
    assert LocalRenderingArtifactStore().exists(str(path))


@pytest.mark.parametrize("name", ["video.mp4", "translation_result.json", "other.ass", "../bilingual.ass"])
def test_stage_cannot_write_upstream_or_escape_staging(tmp_path, name):
    store = LocalRenderingArtifactStore()
    staging = store.plan_staging(str(tmp_path))
    store.create_staging(staging)
    with pytest.raises(ValueError):
        store.stage_bytes(str(Path(staging) / name), b"no")


def test_publish_rejects_other_workspace_and_other_filename(tmp_path):
    store = LocalRenderingArtifactStore()
    staging = Path(store.plan_staging(str(tmp_path)))
    store.create_staging(str(staging))
    source = staging / "bilingual.ass"
    store.stage_bytes(str(source), b"canonical")
    elsewhere = tmp_path / "another"
    elsewhere.mkdir()
    for target in (elsewhere / source.name, tmp_path / "video.mp4"):
        with pytest.raises(ValueError):
            store.publish(str(source), str(target), overwrite=True)
        assert source.read_bytes() == b"canonical"


def test_publish_rejects_symlink_staged_content(tmp_path):
    store = LocalRenderingArtifactStore()
    staging = Path(store.plan_staging(str(tmp_path)))
    store.create_staging(str(staging))
    actual = tmp_path / "actual"
    actual.write_bytes(b"content")
    source = staging / "bilingual.ass"
    source.symlink_to(actual)
    with pytest.raises(ValueError):
        store.publish(str(source), str(tmp_path / source.name), overwrite=False)
    assert actual.read_bytes() == b"content"


def test_system_clock_is_explicit_utc():
    from datetime import datetime
    timestamp = SystemClock().now_utc()
    assert timestamp.endswith("Z")
    assert datetime.fromisoformat(timestamp.replace("Z", "+00:00")).utcoffset().total_seconds() == 0
