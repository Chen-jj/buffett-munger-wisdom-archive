from pathlib import Path

import pytest

from archive_core.interfaces.rendering import RenderProfileDTO, RenderStreamMappingDTO
from infrastructure.infrastructure.process import ProcessBytesResult, ProcessResult
from subtitle_rendering.infrastructure.ffmpeg import FfmpegRenderer, RenderAdapterError, escape_filter_path


class FakeProcesses:
    def __init__(self):
        self.calls = []
        self.filters = " ... ass V->V Render\n ... subtitles V->V Render\n"
        self.encoders = " V....D libx264 H.264\n"
        self.version = "ffmpeg version 9.0.1\nbuild and complete configuration"
        self.libass = "[ass] libass API version: 0x1705000\n[ass] libass source: tarball: 0.17.5\n[ass] Raster: FreeType 2.14.3\n[ass] Shaper: HarfBuzz-ng 14.3.1\n"
        self.libx264 = "[libx264] 264 - core 165 r3222 b35605a - H.264\n[libx264] using cpu capabilities: ARMv8 NEON\n"
        self.frame = bytes([1, 2, 3, 4]) * 8
        self.frame_log = "fontselect complete\nforced line break at 2\n"
        self.fail_render = False

    def text(self, command, **kwargs):
        self.calls.append(("text", command, kwargs))
        if "-version" in command:
            return ProcessResult(tuple(command), 0, self.version, "")
        if "-filters" in command:
            return ProcessResult(tuple(command), 0, self.filters, "")
        if "-encoders" in command:
            return ProcessResult(tuple(command), 0, self.encoders, "")
        if "-vf" in command and "ass=filename=/dev/null" in command:
            return ProcessResult(tuple(command), 234, "", self.libass)
        return ProcessResult(tuple(command), 1 if self.fail_render else 0, "", "mux error" if self.fail_render else "")

    def binary(self, command, **kwargs):
        self.calls.append(("binary", command, kwargs))
        if "-frames:v" in command and command[command.index("-frames:v") + 1] == "0":
            return ProcessBytesResult(tuple(command), 0, b"mp4-header", self.libx264)
        return ProcessBytesResult(tuple(command), 0, self.frame, self.frame_log)

    def renderer(self, **kwargs):
        return FfmpegRenderer(process=self.text, binary_process=self.binary, **kwargs)


def test_canonical_argv_preserves_all_audio_metadata_and_software_profile():
    process = FakeProcesses()
    renderer = process.renderer(executable="/exact/ffmpeg")
    command = renderer.build_command(video_path="/source/video.mp4", ass_path="bilingual.ass", fonts_dir="/font",
                                     output_path="/staging/video.mp4", profile=RenderProfileDTO(), mapping=RenderStreamMappingDTO())
    assert command == ("/exact/ffmpeg", "-nostdin", "-i", "/source/video.mp4", "-vf", "ass=filename=bilingual.ass:fontsdir=/font",
                       "-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                       "-pix_fmt", "yuv420p", "-c:a", "copy", "-fps_mode:v", "passthrough", "-map_metadata", "0",
                       "-map_chapters", "0", "-movflags", "+faststart", "-n", "/staging/video.mp4")
    assert not process.calls
    assert not any(option in command for option in ("-y", "-shortest", "-ss", "-t", "h264_videotoolbox"))
    renderer.render(command, cwd="/staging")
    assert process.calls[-1][2] == {"cwd": "/staging", "timeout": 3600}


def test_filter_path_escapes_both_ffmpeg_parsers():
    assert escape_filter_path("bilingual.ass") == "bilingual.ass"
    assert escape_filter_path("a:b") == r"a\\:b"
    assert escape_filter_path("a'b") == r"a\\\'b"
    assert escape_filter_path("a,b;[c]") == r"a\,b\;\[c\]"
    assert escape_filter_path("a\\b") == r"a\\\\b"
    assert escape_filter_path("a b") == r"a\\\ b"
    for bad in ("", "a\x00b", "a\nb", "a\tb"):
        with pytest.raises(ValueError):
            escape_filter_path(bad)


def test_paths_remain_one_argv_argument_not_shell_text():
    renderer = FakeProcesses().renderer()
    command = renderer.build_command(video_path="/source/a $(touch x);.mp4", ass_path="a'b:c,[d].ass",
                                     fonts_dir="/a font/[dir]", output_path="/staged/out file.mp4", profile=RenderProfileDTO())
    assert command[command.index("-i") + 1] == "/source/a $(touch x);.mp4"
    assert command[-1] == "/staged/out file.mp4"
    assert "ass=filename=" in command[command.index("-vf") + 1]


def test_source_cannot_be_render_target():
    with pytest.raises(ValueError):
        FakeProcesses().renderer().build_command(video_path="/same", ass_path="bilingual.ass", fonts_dir="/font",
                                                 output_path="/same", profile=RenderProfileDTO())


@pytest.mark.parametrize("command", [(), ("other", "-n", "x"), ("ffmpeg", "-y", "x"), ("ffmpeg", "-n", "-shortest", "x")])
def test_unsafe_noncanonical_execution_rejected(command):
    with pytest.raises(ValueError):
        FakeProcesses().renderer().render(command, cwd="/stage")


def test_tool_identity_actual_linked_versions_and_zero_frame_no_files():
    process = FakeProcesses()
    identity = process.renderer().tool_identity(pysubs2_version="1.8.0", ffprobe_version="ffprobe version 9.0.1")
    assert identity.libx264_version == "core 165 r3222 b35605a; cpu: ARMv8 NEON"
    assert identity.libass_version == "0x1705000; tarball: 0.17.5; Raster: FreeType 2.14.3; Shaper: HarfBuzz-ng 14.3.1"
    assert "complete configuration" in identity.ffmpeg_version
    binary = [call for call in process.calls if call[0] == "binary"]
    assert len(binary) == 1 and binary[0][1][-1] == "pipe:1"
    assert binary[0][1][binary[0][1].index("-frames:v") + 1] == "0"
    assert not any("-n" in call[1] for call in process.calls)


@pytest.mark.parametrize("field,value", [("version", "ffmpeg version unknown"), ("filters", "... ass V->V\n"),
                                         ("encoders", "V..... h264_videotoolbox hardware"),
                                         ("libass", "libass API version: 0x1705000"),
                                         ("libass", "libass API version: 0x1705000\nlibass source: unknown"),
                                         ("libx264", "libx264 encoder present")])
def test_unavailable_or_unknown_runtime_identity_rejected(field, value):
    process = FakeProcesses()
    setattr(process, field, value)
    with pytest.raises(RenderAdapterError) as caught:
        process.renderer().tool_identity(pysubs2_version="1.8.0", ffprobe_version="ffprobe version 9.0.1")
    assert caught.value.category == "tool_unavailable"


def test_transparent_frame_is_exact_midpoint_rgba_and_independent_process_per_cue():
    process = FakeProcesses()
    renderer = process.renderer(preflight_timeout=12)
    for midpoint in (1001, 2003):
        frame = renderer.render_transparent_frame(Path("bilingual.ass"), "/exact/fonts", 4, 2, midpoint, cwd="/stage")
        assert frame.rgba == process.frame and frame.stderr == process.frame_log and (frame.width, frame.height) == (4, 2)
        _, command, options = process.calls[-1]
        assert "color=color=black@0:size=4x2,format=rgba,trim=end_frame=1" in command
        assert command[command.index("-vf") + 1] == f"settb=1/1000,setpts=PTS+{midpoint},ass=filename=bilingual.ass:fontsdir=/exact/fonts:alpha=1"
        assert command[command.index("-loglevel") + 1] == "debug"
        assert command[-1] == "pipe:1" and "-frames:v" in command and "rawvideo" in command
        assert options == {"cwd": "/stage", "timeout": 12}
    assert len(process.calls) == 2


@pytest.mark.parametrize("values", [(0, 2, 1), (4, -1, 1), (4, 2, -1), (True, 2, 1), (4, 2, 1.5)])
def test_invalid_frame_request_rejected(values):
    with pytest.raises(ValueError):
        FakeProcesses().renderer().render_transparent_frame("a", "/font", *values)


def test_short_raw_frame_and_log_truncation_never_pass():
    process = FakeProcesses()
    process.frame = b""
    with pytest.raises(RenderAdapterError) as caught:
        process.renderer().render_transparent_frame("a", "/font", 4, 2, 1)
    assert caught.value.category == "render_validation_failed"
    process = FakeProcesses()
    with pytest.raises(RenderAdapterError, match="render_failed"):
        process.renderer(maximum_log_bytes=1).render_transparent_frame("a", "/font", 4, 2, 1)


@pytest.mark.parametrize("code,dry_run,category", [(1, False, "render_failed"), (124, False, "render_failed"),
                                                   (127, False, "tool_unavailable"), (0, True, "tool_unavailable")])
def test_binary_failures_are_controlled(code, dry_run, category):
    def binary(command, **kwargs):
        return ProcessBytesResult(tuple(command), code, b"", "diagnostic", dry_run)
    with pytest.raises(RenderAdapterError) as caught:
        FfmpegRenderer(binary_process=binary).render_transparent_frame("a", "/font", 4, 2, 1)
    assert caught.value.category == category


def test_audio_mux_failure_is_not_retried_or_transcoded():
    process = FakeProcesses()
    process.fail_render = True
    renderer = process.renderer()
    command = renderer.build_command(video_path="/video", ass_path="bilingual.ass", fonts_dir="/font",
                                     output_path="/stage/out.mp4", profile=RenderProfileDTO())
    with pytest.raises(RenderAdapterError) as caught:
        renderer.render(command, cwd="/stage")
    assert caught.value.category == "render_failed" and caught.value.diagnostic == "mux error"
    assert len(process.calls) == 1 and command[command.index("-c:a") + 1] == "copy"


def test_process_interrupt_is_controlled_and_not_exposed():
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt("private/path")
    with pytest.raises(RenderAdapterError) as caught:
        FfmpegRenderer(process=interrupted).render(("ffmpeg", "-n", "out"), cwd="/stage")
    assert caught.value.category == "render_failed" and "private/path" not in str(caught.value)


@pytest.mark.parametrize("pysubs2,ffprobe", [("unknown", "ffprobe version 9.0.1"), ("1.8.0", "ffprobe version unknown")])
def test_unknown_ass_or_probe_identity_is_rejected(pysubs2, ffprobe):
    with pytest.raises(RenderAdapterError) as caught:
        FakeProcesses().renderer().tool_identity(pysubs2_version=pysubs2, ffprobe_version=ffprobe)
    assert caught.value.category == "tool_unavailable"


def test_libass_timeout_with_partial_identity_must_not_pass():
    processes = FakeProcesses()
    def process(command, **kwargs):
        result = processes.text(command, **kwargs)
        if "ass=filename=/dev/null" in command:
            return ProcessResult(tuple(command), 124, "", processes.libass)
        return result
    with pytest.raises(RenderAdapterError) as caught:
        FfmpegRenderer(process=process, binary_process=processes.binary).tool_identity(
            pysubs2_version="1.8.0", ffprobe_version="ffprobe version 9.0.1")
    assert caught.value.category == "tool_unavailable"
