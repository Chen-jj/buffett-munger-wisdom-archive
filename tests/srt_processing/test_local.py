from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from srt_processing.infrastructure.local import (
    LocalSubtitleArtifactStore, SystemClock, json_bytes,
)


def test_json_bytes_are_stable_utf8_lf_and_have_a_terminal_newline() -> None:
    value = {"z": "中文", "a": {"second": 2, "first": 1}, "escaped": "a\nb"}
    data = json_bytes(value)
    assert data == json_bytes(dict(reversed(list(value.items()))))
    assert data == (
        '{\n  "a": {\n    "first": 1,\n    "second": 2\n  },\n'
        '  "escaped": "a\\nb",\n  "z": "中文"\n}\n'
    ).encode("utf-8")
    assert b"\r" not in data and not data.startswith(b"\xef\xbb\xbf")
    assert json.loads(data.decode("utf-8")) == value


@pytest.mark.parametrize("value", [[], None, {"bad": float("nan")}, {"bad": float("inf")}, {"bad": object()}])
def test_json_bytes_reject_non_objects_non_finite_numbers_and_non_json_values(value) -> None:
    with pytest.raises((ValueError, TypeError)):
        json_bytes(value)


def test_store_reads_and_hashes_full_bytes_without_loading_video_for_hash(tmp_path) -> None:
    store = LocalSubtitleArtifactStore()
    path = tmp_path / "video.mp4"
    data = b"chunk" * (1024 * 1024)
    path.write_bytes(data)
    assert store.exists(str(path))
    assert store.size(str(path)) == len(data)
    assert store.sha256(str(path)) == hashlib.sha256(data).hexdigest()
    assert store.read_bytes(str(path)) == data
    assert not store.exists(str(tmp_path / "missing"))


def test_stage_is_same_directory_and_does_not_modify_existing_target(tmp_path) -> None:
    store = LocalSubtitleArtifactStore()
    target = tmp_path / "asset" / "subtitle_plan.json"
    target.parent.mkdir()
    target.write_bytes(b"old complete contents")
    staged = Path(store.stage_bytes(str(target), b"new complete contents"))
    assert staged.parent == target.parent
    assert staged.name.startswith(".subtitle_plan.json.") and staged.name.endswith(".tmp")
    assert staged.read_bytes() == b"new complete contents"
    assert target.read_bytes() == b"old complete contents"


def test_stage_creates_workspace_but_never_creates_formal_target(tmp_path) -> None:
    store = LocalSubtitleArtifactStore()
    target = tmp_path / "new" / "asset" / "english.srt"
    staged = Path(store.stage_bytes(str(target), b"prepared"))
    assert target.parent.is_dir() and staged.is_file()
    assert not target.exists()


@pytest.mark.parametrize("data", ["not bytes", None, bytearray(b"not immutable")])
def test_stage_rejects_non_bytes_before_creating_any_file(tmp_path, data) -> None:
    with pytest.raises(ValueError, match="must be bytes"):
        LocalSubtitleArtifactStore().stage_bytes(str(tmp_path / "new" / "english.srt"), data)
    assert list(tmp_path.iterdir()) == []


def test_publish_atomically_replaces_exactly_one_prepared_target(tmp_path) -> None:
    store = LocalSubtitleArtifactStore()
    target = tmp_path / "english.srt"
    staged = store.stage_bytes(str(target), b"new")
    store.publish(staged, str(target), overwrite=False)
    assert target.read_bytes() == b"new"
    assert not Path(staged).exists()  # consumed by rename, never by cleanup/unlink
    staged = store.stage_bytes(str(target), b"updated")
    store.publish(staged, str(target), overwrite=True)
    assert target.read_bytes() == b"updated"


def test_publish_default_conflict_preserves_both_target_and_staging(tmp_path) -> None:
    store = LocalSubtitleArtifactStore()
    target = tmp_path / "english.srt"
    target.write_bytes(b"old")
    staged = store.stage_bytes(str(target), b"new")
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        store.publish(staged, str(target), overwrite=False)
    assert target.read_bytes() == b"old"
    assert Path(staged).read_bytes() == b"new"


def test_broken_symlink_is_an_existing_target_not_an_automatic_overwrite(tmp_path) -> None:
    store = LocalSubtitleArtifactStore()
    target = tmp_path / "english.srt"
    target.symlink_to(tmp_path / "absent.srt")
    staged = store.stage_bytes(str(target), b"new")
    assert store.exists(str(target))
    with pytest.raises(FileExistsError):
        store.publish(staged, str(target), overwrite=False)
    assert target.is_symlink() and Path(staged).exists()


def test_publish_refuses_cross_directory_staging_without_moving_either_file(tmp_path) -> None:
    store = LocalSubtitleArtifactStore()
    first = tmp_path / "first" / "english.srt"
    staged = store.stage_bytes(str(first), b"new")
    second = tmp_path / "second" / "english.srt"
    second.parent.mkdir()
    with pytest.raises(ValueError, match="share a directory"):
        store.publish(staged, str(second), overwrite=False)
    assert Path(staged).read_bytes() == b"new" and not second.exists()


def test_publish_cannot_mistake_source_media_for_a_staged_output(tmp_path) -> None:
    store = LocalSubtitleArtifactStore()
    source = tmp_path / "video.mp4"
    source.write_bytes(b"source media")
    with pytest.raises(ValueError, match="requires a staging file"):
        store.publish(str(source), str(tmp_path / "english.srt"), overwrite=True)
    assert source.read_bytes() == b"source media"


def test_failed_staging_preserves_partial_temporary_file_and_old_target(tmp_path, monkeypatch) -> None:
    import srt_processing.infrastructure.local as module

    target = tmp_path / "subtitle_plan.json"
    target.write_bytes(b"old plan")
    real_factory = module.NamedTemporaryFile
    temporary_paths = []

    class FailingWrite:
        def __init__(self, stream):
            self.stream = stream
            self.name = stream.name

        def __enter__(self):
            return self

        def write(self, data):
            self.stream.write(data[:4])
            self.stream.flush()
            raise OSError("disk full")

        def __exit__(self, *args):
            self.stream.close()

    def failing_factory(*args, **kwargs):
        assert kwargs["delete"] is False
        stream = real_factory(*args, **kwargs)
        temporary_paths.append(Path(stream.name))
        return FailingWrite(stream)

    monkeypatch.setattr(module, "NamedTemporaryFile", failing_factory)
    with pytest.raises(OSError, match="disk full"):
        module.LocalSubtitleArtifactStore().stage_bytes(str(target), b"prepared data")
    assert target.read_bytes() == b"old plan"
    assert len(temporary_paths) == 1 and temporary_paths[0].read_bytes() == b"prep"


def test_failed_replace_preserves_old_complete_target_and_staged_file(tmp_path, monkeypatch) -> None:
    store = LocalSubtitleArtifactStore()
    target = tmp_path / "subtitle_plan.json"
    target.write_bytes(b"old plan")
    staged = store.stage_bytes(str(target), b"new plan")
    calls = []

    def failing_replace(source, destination):
        calls.append((source, destination))
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", failing_replace)
    with pytest.raises(OSError, match="replace failed"):
        store.publish(staged, str(target), overwrite=True)
    assert calls == [(Path(staged), target)]
    assert target.read_bytes() == b"old plan"
    assert Path(staged).read_bytes() == b"new plan"


def test_single_file_publication_is_not_a_multi_file_transaction(tmp_path, monkeypatch) -> None:
    store = LocalSubtitleArtifactStore()
    paths = tuple(tmp_path / name for name in ("english.srt", "chinese.srt", "srt_processing_manifest.json"))
    for path in paths:
        path.write_bytes(b"old " + path.name.encode())
    staged = tuple(store.stage_bytes(str(path), b"new " + path.name.encode()) for path in paths)
    real_replace = Path.replace

    def fail_second(source, destination):
        if destination == paths[1]:
            raise OSError("second rename failed")
        return real_replace(source, destination)

    monkeypatch.setattr(Path, "replace", fail_second)
    store.publish(staged[0], str(paths[0]), overwrite=True)
    with pytest.raises(OSError):
        store.publish(staged[1], str(paths[1]), overwrite=True)
    assert paths[0].read_bytes() == b"new english.srt"
    assert paths[1].read_bytes() == b"old chinese.srt"
    assert paths[2].read_bytes() == b"old srt_processing_manifest.json"
    assert Path(staged[1]).exists() and Path(staged[2]).exists()


def test_missing_input_files_raise_io_errors_without_synthesizing_evidence(tmp_path) -> None:
    store = LocalSubtitleArtifactStore()
    for operation in (store.read_bytes, store.size, store.sha256):
        with pytest.raises(FileNotFoundError):
            operation(str(tmp_path / "missing"))


def test_system_clock_returns_explicit_utc_iso_timestamp(monkeypatch) -> None:
    import srt_processing.infrastructure.local as module

    class FixedDatetime:
        @classmethod
        def now(cls, tz):
            assert tz is timezone.utc
            return datetime(2026, 10, 21, 3, 4, 5, 123456, tzinfo=tz)

    monkeypatch.setattr(module, "datetime", FixedDatetime)
    assert SystemClock().now_utc() == "2026-10-21T03:04:05.123456Z"
