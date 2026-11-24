"""Decoded media boundary adapter in isolation; subprocess and checksum are fakes."""
from decimal import InvalidOperation
import json

import pytest

from archive_core.interfaces.bilingual import ArtifactEvidenceDTO
from infrastructure.infrastructure.process import ProcessExecutionError, ProcessResult
from media_download.infrastructure import media_boundary


VIDEO = "/archive/video with spaces.mp4"
SHA = "b" * 64


@pytest.fixture
def isolated_evidence(monkeypatch):
    paths = []

    def evidence(path):
        paths.append(path)
        return ArtifactEvidenceDTO(path, 42, SHA)

    monkeypatch.setattr(media_boundary, "evidence", evidence)
    return paths


def decoded(**overrides):
    return {
        "streams": [{"width": 640, "height": 360, "start_time": "2.100000", "duration": "1.234999"}],
        "format": {"start_time": "2.100000", "duration": "1.440000"},
        "frames": [
            {"best_effort_timestamp_time": "2.100000"},
            {"best_effort_timestamp_time": "2.132001"},
            {"best_effort_timestamp_time": "2.189000"},
        ],
    } | overrides


def response(data):
    def process(command, **options):
        assert options == {"check": True}
        return ProcessResult(tuple(command), 0, json.dumps(data), "")
    return process


def test_probe_uses_injected_argv_and_binds_exact_source_relative_decoded_pts(isolated_evidence):
    commands = []

    def process(command, **options):
        commands.append(command)
        return response(decoded())(command, **options)

    boundary, stream = media_boundary.probe_video_boundary(VIDEO, process)
    assert commands == [
        [media_boundary.FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_frames",
         "-show_format", "-show_streams", "-show_entries",
         "frame=best_effort_timestamp_time:format=start_time,duration:stream=width,height,start_time,duration",
         "-of", "json", VIDEO],
    ]
    assert isolated_evidence == [VIDEO]
    assert boundary.video_sha256 == SHA
    assert boundary.duration_ms == 1234
    assert boundary.frame_timestamps_us == (0, 32001, 89000)
    assert (stream["width"], stream["height"]) == (640, 360)


@pytest.mark.parametrize("frames", [
    [],
    None,
    [{}],
    [{"best_effort_timestamp_time": "2.099999"}],
    [{"best_effort_timestamp_time": "2.100000"}, {"best_effort_timestamp_time": "2.100000"}],
    [{"best_effort_timestamp_time": "2.200000"}, {"best_effort_timestamp_time": "2.150000"}],
    [{"best_effort_timestamp_time": "3.334000"}],
])
def test_missing_or_unreliable_frame_evidence_stays_unknown(isolated_evidence, frames):
    data = decoded(frames=frames)
    data["streams"][0]["avg_frame_rate"] = "24/1"
    boundary, _ = media_boundary.probe_video_boundary(VIDEO, response(data))
    assert boundary.duration_ms == 1234 and boundary.video_sha256 == SHA
    assert boundary.frame_timestamps_us is None


@pytest.mark.parametrize("duration", ["0", "-1", "NaN", "Infinity", "N/A", "0.0009", None])
def test_unusable_container_duration_cannot_create_media_evidence(isolated_evidence, duration):
    # A valid video duration may legitimately bound an unbounded container duration.
    # Put the same invalid probe value on both boundaries.
    data = decoded(format={"duration": duration}, streams=[{"duration": duration}])
    with pytest.raises((ValueError, InvalidOperation, TypeError, OverflowError)):
        media_boundary.probe_video_boundary(VIDEO, response(data))


@pytest.mark.parametrize("data", [[], {}, {"streams": []}, {"streams": [{}]}, decoded(format=[])])
def test_malformed_probe_envelope_is_not_media_evidence(isolated_evidence, data):
    with pytest.raises((ValueError, TypeError, KeyError, IndexError, AttributeError)):
        media_boundary.probe_video_boundary(VIDEO, response(data))
    assert not isolated_evidence


def test_probe_does_not_swallow_nonzero_checked_process_failure(isolated_evidence):
    def process(command, **options):
        assert options["check"] is True
        raise ProcessExecutionError(ProcessResult(tuple(command), 1, json.dumps(decoded()), "injected failure"))

    with pytest.raises(ProcessExecutionError, match="injected failure"):
        media_boundary.probe_video_boundary(VIDEO, process)
    assert not isolated_evidence


def test_probe_does_not_swallow_process_exceptions(isolated_evidence):
    def process(command, **options):
        raise OSError("missing tool")

    with pytest.raises(OSError, match="missing tool"):
        media_boundary.probe_video_boundary(VIDEO, process)
    assert not isolated_evidence


@pytest.mark.parametrize("payload,dry_run", [("not json", False), ("", True)])
def test_invalid_or_dry_run_stdout_is_not_media_evidence(isolated_evidence, payload, dry_run):
    def process(command, **options):
        return ProcessResult(tuple(command), 0, payload, "", dry_run=dry_run)

    with pytest.raises(ValueError):
        media_boundary.probe_video_boundary(VIDEO, process)
    assert not isolated_evidence


@pytest.mark.parametrize("rate", ["0/1", "24/0", "0/0", "-24/1", "24", "N/A", None, 24, "NaN/1"])
def test_invalid_average_rate_cannot_supply_missing_actual_frames(isolated_evidence, rate):
    data = decoded(frames=[])
    data["streams"][0]["avg_frame_rate"] = rate
    boundary, _ = media_boundary.probe_video_boundary(VIDEO, response(data))
    assert boundary.frame_timestamps_us is None
    assert boundary.duration_ms == 1234


@pytest.mark.parametrize("duration", [2, True])
@pytest.mark.parametrize("field", ["format", "stream"])
def test_duration_requires_ffprobe_json_string(isolated_evidence, field, duration):
    data = decoded()
    target = data["format"] if field == "format" else data["streams"][0]
    target["duration"] = duration
    with pytest.raises(ValueError, match="duration must be a JSON string"):
        media_boundary.probe_video_boundary(VIDEO, response(data))
    assert not isolated_evidence


def test_probe_requires_exactly_one_selected_video_stream(isolated_evidence):
    data = decoded()
    data["streams"].append(dict(data["streams"][0]))
    with pytest.raises(ValueError, match="exactly one selected video stream"):
        media_boundary.probe_video_boundary(VIDEO, response(data))
    assert not isolated_evidence
