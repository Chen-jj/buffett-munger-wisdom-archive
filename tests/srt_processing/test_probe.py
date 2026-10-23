from __future__ import annotations

import json

import pytest

from infrastructure.infrastructure.process import ProcessResult
from srt_processing.infrastructure.probe import FfprobeMediaProbe


class FakeProcess:
    def __init__(self, data=None, *, version="ffprobe version 9.0\nconfiguration: fake\n"):
        self.data = data if data is not None else {
            "streams": [{"avg_frame_rate": "48000/2000"}], "format": {"duration": "1.234999"},
        }
        self.version = version
        self.calls = []
        self.fail_on = None
        self.dry_run = False

    def __call__(self, command, **options):
        self.calls.append((command, options))
        stdout = self.version if command[-1] == "-version" else json.dumps(self.data)
        return ProcessResult(tuple(command), 1 if len(self.calls) == self.fail_on else 0,
                             stdout, "failed", dry_run=self.dry_run)


def test_probe_uses_injected_argv_and_preserves_rational() -> None:
    process = FakeProcess()
    probe = FfprobeMediaProbe(executable="/tools/ffprobe", process=process, timeout=12)
    result = probe.probe("/asset/video with spaces.mp4")
    assert result.video_duration_ms == 1234
    assert (result.fps_numerator, result.fps_denominator) == (48000, 2000)
    assert result.tool_version == "ffprobe version 9.0"
    assert process.calls == [
        (["/tools/ffprobe", "-version"], {"check": True, "timeout": 12}),
        (["/tools/ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
          "stream=avg_frame_rate:format=duration", "-of", "json", "/asset/video with spaces.mp4"],
         {"check": True, "timeout": 12}),
    ]


@pytest.mark.parametrize("rate", ["0/1", "24/0", "0/0", "-24/1", "24", "N/A", None, 24, "NaN/1"])
def test_probe_rejects_invalid_frame_rate_without_guessing(rate) -> None:
    process = FakeProcess({"streams": [{"avg_frame_rate": rate}], "format": {"duration": "2"}})
    with pytest.raises(ValueError):
        FfprobeMediaProbe(process=process).probe("video.mp4")


@pytest.mark.parametrize("duration", ["0", "-1", "NaN", "Infinity", "N/A", "0.0009", None, 2, True])
def test_probe_rejects_invalid_duration(duration) -> None:
    process = FakeProcess({"streams": [{"avg_frame_rate": "24/1"}], "format": {"duration": duration}})
    with pytest.raises(ValueError):
        FfprobeMediaProbe(process=process).probe("video.mp4")


@pytest.mark.parametrize("data", [[], {}, {"streams": []}, {"streams": [{}]},
                                    {"streams": [{"avg_frame_rate": "24/1"}]},
                                    {"streams": [{"avg_frame_rate": "24/1"}], "format": []},
                                    {"streams": [{}, {}], "format": {"duration": "1"}}])
def test_probe_rejects_unusable_media(data) -> None:
    with pytest.raises(ValueError):
        FfprobeMediaProbe(process=FakeProcess(data)).probe("video.mp4")


@pytest.mark.parametrize("version", ["", "not ffprobe", "ffprobe\n", "ffprobe version \n"])
def test_probe_requires_tool_version(version) -> None:
    process = FakeProcess(version=version)
    with pytest.raises(ValueError):
        FfprobeMediaProbe(process=process).probe("video.mp4")
    assert len(process.calls) == 1


@pytest.mark.parametrize("fail_on", [1, 2])
def test_probe_rejects_nonzero_exit_even_with_valid_stdout(fail_on) -> None:
    process = FakeProcess()
    process.fail_on = fail_on
    with pytest.raises(ValueError):
        FfprobeMediaProbe(process=process).probe("video.mp4")


def test_probe_cannot_treat_dry_run_as_real_evidence() -> None:
    process = FakeProcess()
    process.dry_run = True
    with pytest.raises(ValueError):
        FfprobeMediaProbe(process=process).probe("video.mp4")


def test_probe_does_not_swallow_process_exceptions() -> None:
    def failing_process(command, **options):
        raise OSError("missing tool")

    with pytest.raises(OSError, match="missing tool"):
        FfprobeMediaProbe(process=failing_process).probe("video.mp4")


def test_probe_rejects_invalid_json() -> None:
    process = FakeProcess()

    def invalid_json(command, **options):
        result = process(command, **options)
        if command[-1] == "-version":
            return result
        return ProcessResult(tuple(command), 0, "not json", "")

    with pytest.raises(ValueError):
        FfprobeMediaProbe(process=invalid_json).probe("video.mp4")
