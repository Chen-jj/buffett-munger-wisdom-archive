from copy import deepcopy
from dataclasses import replace
import json

import pytest

from archive_core.interfaces.rendering import RenderTagDTO
from infrastructure.infrastructure.process import ProcessResult
from subtitle_rendering.infrastructure.probe import (
    FfprobeMediaProbe, MediaProbeError, parse_media, validate_rendered_media,
)


def media_json():
    return {"streams": [
        {"index": 0, "codec_type": "video", "codec_name": "h264", "width": 640, "height": 360,
         "sample_aspect_ratio": "1:1", "display_aspect_ratio": "16:9", "avg_frame_rate": "30/1",
         "r_frame_rate": "30/1", "time_base": "1/15360", "start_time": "0.000000", "duration": "0.100000",
         "nb_frames": "3", "pix_fmt": "yuv420p", "tags": {"title": "video", "encoder": "old"}},
        {"index": 1, "codec_type": "audio", "codec_name": "aac", "sample_rate": "44100", "channels": 2,
         "channel_layout": "stereo", "start_time": "0.000000", "duration": "0.100000",
         "disposition": {"default": 1}, "tags": {"language": "eng", "title": "audio"}},
    ], "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "start_time": "0.000000", "duration": "0.100000",
                  "tags": {"title": "sample", "encoder": "old", "major_brand": "isom"}}, "chapters": []}


def result(command, value, *, code=0, stderr="", dry_run=False):
    return ProcessResult(tuple(command), code, json.dumps(value) if not isinstance(value, str) else value, stderr, dry_run)


class FakeProbeProcess:
    def __init__(self, *, data=None, frames=None, packets=None):
        self.data = data if data is not None else media_json()
        self.frames = frames if frames is not None else [{"media_type": "video", "width": 640, "height": 360, "pix_fmt": "yuv420p"}]
        # Coded packet order is not presentation order (B frames).
        self.packets = packets if packets is not None else [{"pts": x, "duration": 512} for x in (0, 1024, 512)]
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if "-version" in command:
            return result(command, "ffprobe version 9.0.1\nbuild identity")
        if "-show_frames" in command:
            return result(command, {"frames": self.frames})
        if "-show_packets" in command:
            return result(command, {"packets": self.packets})
        return result(command, self.data)


def test_probe_uses_injected_process_and_complete_evidence():
    process = FakeProbeProcess()
    probe = FfprobeMediaProbe(executable="/exact/ffprobe", process=process, timeout=7)
    assert probe.version() == "ffprobe version 9.0.1\nbuild identity"
    media = probe.probe("/path/video.mp4")
    assert media.video.duration_us == 100000 and media.video.frame_count == 3
    assert media.audio_streams[0].sample_rate == 44100
    assert len(process.calls) == 4
    assert all(call[0][0] == "/exact/ffprobe" and call[1]["timeout"] == 7 for call in process.calls)
    assert "-show_chapters" in process.calls[1][0]
    assert "%+#1" in process.calls[2][0]
    assert "-read_intervals" not in process.calls[3][0]  # all packets, not a CFR guess


def test_decimal_microseconds_no_float_and_optional_audio_duration():
    data = media_json()
    data["streams"][0]["start_time"] = "0.000001"
    data["streams"][0]["duration"] = "623.000001"
    data["streams"][1].pop("duration")
    media = parse_media(data)
    assert media.video.start_time_us == 1 and media.video.duration_us == 623000001
    assert media.audio_streams[0].duration_us is None


@pytest.mark.parametrize("key,value", [
    ("width", True), ("width", 0), ("height", "oops"), ("codec_name", ""),
    ("pix_fmt", None), ("start_time", None), ("duration", "N/A"), ("duration", "NaN"),
    ("duration", "Infinity"), ("duration", "0"), ("duration", 0.1),
    ("sample_aspect_ratio", "4:3"), ("sample_aspect_ratio", "0:1"),
    ("display_aspect_ratio", "2:1"), ("avg_frame_rate", "0/0"), ("avg_frame_rate", "29/1"),
    ("r_frame_rate", "N/A"), ("nb_frames", True), ("nb_frames", "0"),
    ("tags", {"title": 3}), ("tags", {"rotate": "90"}),
    ("side_data_list", [{"side_data_type": "Display Matrix"}]),
    ("side_data_list", [{"rotation": 180}]), ("disposition", {"attached_pic": 1}),
])
def test_invalid_or_unexplained_video_is_rejected(key, value):
    data = media_json()
    data["streams"][0][key] = value
    with pytest.raises(MediaProbeError):
        parse_media(data)


@pytest.mark.parametrize("key", ["duration", "start_time", "width", "height", "pix_fmt", "codec_name", "sample_aspect_ratio", "display_aspect_ratio"])
def test_missing_video_fields_are_not_guessed(key):
    data = media_json()
    data["streams"][0].pop(key)
    with pytest.raises(MediaProbeError):
        parse_media(data)


@pytest.mark.parametrize("data", [None, [], {}, {"streams": [], "format": {}}, {"streams": [None], "format": {}},
                                  {"streams": [{"index": True}], "format": {}}])
def test_invalid_json_shape(data):
    with pytest.raises(MediaProbeError):
        parse_media(data)


@pytest.mark.parametrize("key,value", [("sample_rate", "0"), ("channels", True), ("channel_layout", ""),
                                      ("disposition", {"default": 2}), ("duration", "NaN"), ("tags", [])])
def test_invalid_audio_is_rejected(key, value):
    data = media_json()
    data["streams"][1][key] = value
    with pytest.raises(MediaProbeError):
        parse_media(data)


def test_duplicate_streams_and_bad_chapter_are_rejected():
    data = media_json()
    data["streams"].append(deepcopy(data["streams"][1]))
    with pytest.raises(MediaProbeError):
        parse_media(data)
    data = media_json()
    data["chapters"] = [{"id": 0, "start_time": "0", "end_time": "1", "tags": {}}]
    with pytest.raises(MediaProbeError):
        parse_media(data)


@pytest.mark.parametrize("frames", [[], [None], [{"media_type": "audio"}],
                                     [{"media_type": "video", "width": 641, "height": 360, "pix_fmt": "yuv420p"}]])
def test_first_video_must_actually_decode(frames):
    with pytest.raises(MediaProbeError):
        FfprobeMediaProbe(process=FakeProbeProcess(frames=frames)).probe("video.mp4")


@pytest.mark.parametrize("packets", [[], [None], [{"pts": 0}], [{"duration": 512}],
    [{"pts": True, "duration": 512}], [{"pts": 0, "duration": 511}],
    [{"pts": 0, "duration": 512}, {"pts": 512, "duration": 512}],
    [{"pts": 0, "duration": 512}, {"pts": 512, "duration": 512}, {"pts": 512, "duration": 512}],
    [{"pts": 0, "duration": 512}, {"pts": 511, "duration": 512}, {"pts": 1024, "duration": 512}],
])
def test_vfr_missing_or_inconsistent_packet_evidence_is_rejected(packets):
    with pytest.raises(MediaProbeError):
        FfprobeMediaProbe(process=FakeProbeProcess(packets=packets)).probe("video.mp4")


def test_packet_duration_must_agree_with_video_duration():
    process = FakeProbeProcess()
    process.data["streams"][0]["duration"] = "1.0"
    with pytest.raises(MediaProbeError):
        FfprobeMediaProbe(process=process).probe("video.mp4")


@pytest.mark.parametrize("stdout,code,stderr,dry_run", [("[]", 0, "", False), ("not-json", 0, "", False),
    ("{}", 1, "", False), ("{}", 0, "decode error", False), ("{}", 0, "", True)])
def test_probe_errors_and_malformed_outputs_are_controlled(stdout, code, stderr, dry_run):
    def process(command, **kwargs):
        return result(command, stdout, code=code, stderr=stderr, dry_run=dry_run)
    with pytest.raises(MediaProbeError):
        FfprobeMediaProbe(process=process).probe("video.mp4")


@pytest.mark.parametrize("version", ["", "ffprobe version unknown", "ffmpeg version 9.0.1"])
def test_unknown_probe_version_rejected(version):
    with pytest.raises(MediaProbeError):
        FfprobeMediaProbe(process=lambda command, **k: result(command, version)).version()


def test_probe_interrupt_and_missing_binary_are_controlled():
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt()
    with pytest.raises(MediaProbeError):
        FfprobeMediaProbe(process=interrupted).probe("video.mp4")


def test_output_validation_preserves_content_but_not_muxer_bookkeeping():
    source = parse_media(media_json())
    tags = (RenderTagDTO("encoder", "new"), RenderTagDTO("title", "sample"))
    validate_rendered_media(source, replace(source, tags=tags), 100)


@pytest.mark.parametrize("changes", [
    {"format_name": "matroska"}, {"video_stream_count": 2}, {"subtitle_stream_count": 1}, {"data_stream_count": 1},
    {"audio_streams": ()}, {"tags": ()},
])
def test_output_container_stream_or_metadata_mismatch(changes):
    source = parse_media(media_json())
    with pytest.raises(MediaProbeError):
        validate_rendered_media(source, replace(source, **changes), 99)


@pytest.mark.parametrize("changes", [
    {"codec_name": "hevc"}, {"pixel_format": "yuv444p"}, {"width": 1280, "height": 720},
    {"fps_numerator": 60, "r_fps_numerator": 60}, {"duration_us": 133334}, {"start_time_us": 33334},
    {"frame_count": 2}, {"rotation_degrees": 90}, {"tags": ()},
])
def test_output_video_mismatch(changes):
    source = parse_media(media_json())
    with pytest.raises(MediaProbeError):
        validate_rendered_media(source, replace(source, video=replace(source.video, **changes)), 99)


def test_exact_rational_one_frame_tolerance_and_cue_duration():
    source = parse_media(media_json())
    validate_rendered_media(source, replace(source, video=replace(source.video, duration_us=133333)), 100)
    with pytest.raises(MediaProbeError):
        validate_rendered_media(source, source, 101)
    with pytest.raises(MediaProbeError):
        validate_rendered_media(source, source, True)


@pytest.mark.parametrize("changes", [
    {"codec_name": "mp3"}, {"sample_rate": 48000}, {"channels": 1, "channel_layout": "mono"},
    {"default": False}, {"start_time_us": 1}, {"duration_us": 100001}, {"tags": ()},
])
def test_all_audio_properties_and_metadata_preserved(changes):
    source = parse_media(media_json())
    output = replace(source, audio_streams=(replace(source.audio_streams[0], **changes),))
    with pytest.raises(MediaProbeError):
        validate_rendered_media(source, output, 99)


def test_packet_pts_must_agree_with_video_start():
    process = FakeProbeProcess(packets=[{"pts": x, "duration": 512} for x in (512, 1024, 1536)])
    with pytest.raises(MediaProbeError):
        FfprobeMediaProbe(process=process).probe("video.mp4")
