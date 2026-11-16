"""Explicit, auditable local media derivation from a verified downloaded parent."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from archive_core.application import build_asset_workspace
from archive_core.interfaces import StructuredTranscriptDTO
from archive_core.interfaces.bilingual import MediaBoundaryDTO, StageManifestDTO
from infrastructure.infrastructure.artifacts import evidence, read_json, verify_evidence, verify_stage_manifest, write_json
from infrastructure.infrastructure.process import run_process
from media_download.domain import DownloadedArtifact, MediaRef
from .composition import LocalDownloadHandler
from .media_boundary import FFMPEG, FFPROBE, probe_video_boundary


class LocalMediaDerivationHandler:
    def __init__(self, *, output_root, process_runner=None):
        self.root = str(Path(output_root).resolve())
        self.process = process_runner or run_process

    def _paths(self, command):
        parent = build_asset_workspace(command.parent_asset_id, self.root)
        target = build_asset_workspace(command.asset_id, self.root)
        return parent, target

    def _identity(self, command):
        return {"policy": "source-media-derivation.v1", "parent_asset_id": command.parent_asset_id.value,
                "start_ms": command.start_ms, "end_ms": command.end_ms,
                "chapter_numbers": list(command.chapter_numbers),
                "time_mapping": {"source_start_ms": command.start_ms, "derived_start_ms": 0,
                                 "duration_ms": command.end_ms - command.start_ms}}

    def verify(self, command):
        parent, target = self._paths(command)
        inputs = {name: parent / filename for name, filename in self._input_names().items()}
        outputs = {name: target / filename for name, filename in self._output_names().items()}
        manifest = verify_stage_manifest(target / "media_derivation_manifest.json", stage="media_derivation",
                                         asset_id=command.asset_id.value, inputs=inputs, outputs=outputs)
        # thaw JSON array tuples before comparing to the explicit request.
        identity = manifest.to_dict()["identity"]
        if set(identity) != {"request", "command", "tool", "audio_codec", "duration_tolerance_ms"} or identity["request"] != self._identity(command):
            raise ValueError("media derivation request changed")
        transcript = StructuredTranscriptDTO.from_dict(read_json(target / "chapters.json"))
        if tuple(chapter.number for chapter in transcript.chapters) != command.chapter_numbers:
            raise ValueError("derived transcript chapters do not match selection")
        media = MediaBoundaryDTO.from_dict(read_json(target / "media_boundary.json"))
        if media.video_sha256 != manifest.outputs["video"].sha256 or abs(media.duration_ms - (command.end_ms - command.start_ms)) > 50:
            raise ValueError("derived media boundary does not match selected range")
        # Reapply the normal download evidence gate without any network resolution.
        from media_download.interfaces.workflow import DownloadCommand
        LocalDownloadHandler(output_root=self.root).verify(DownloadCommand(command.asset_id))
        return manifest

    @staticmethod
    def _input_names():
        return {"parent_acquisition": "acquisition_receipt.json", "parent_meta": "meta.json",
                "parent_chapters": "chapters.json", "parent_download": "download_manifest.json", "parent_video": "video.mp4"}

    @staticmethod
    def _output_names():
        return {"meta": "meta.json", "media_ref": "media_ref.json", "chapters": "chapters.json", "transcript": "transcript.txt",
                "video": "video.mp4", "download_manifest": "download_manifest.json", "media_boundary": "media_boundary.json"}

    def handle(self, command):
        parent, target = self._paths(command)
        manifest_path = target / "media_derivation_manifest.json"
        if manifest_path.exists():
            self.verify(command)
            return {"status": "reused", "manifest_path": str(manifest_path), "media_derivation_encoding_calls": 0, "writes": 0}
        if any((target / name).exists() for name in self._output_names().values()):
            raise ValueError("media derivation artifact conflict: partial outputs")
        from media_download.interfaces.workflow import DownloadCommand
        LocalDownloadHandler(output_root=self.root).verify(DownloadCommand(command.parent_asset_id))
        acquisition = verify_stage_manifest(parent / "acquisition_receipt.json", stage="acquisition", asset_id=command.parent_asset_id.value, inputs={})
        if "chapters" not in acquisition.outputs:
            raise ValueError("media derivation requires source transcript chapters")
        source = StructuredTranscriptDTO.from_dict(read_json(parent / "chapters.json"))
        selected = tuple(chapter for chapter in source.chapters if chapter.number in command.chapter_numbers)
        if tuple(chapter.number for chapter in selected) != command.chapter_numbers:
            raise ValueError("requested source chapters are absent or out of order")
        transcript = StructuredTranscriptDTO("en", selected)
        input_evidence = {name: evidence(parent / filename) for name, filename in self._input_names().items()}
        parent_probe = self.process([FFPROBE, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(parent / "video.mp4")], check=True)
        import json
        probe = json.loads(parent_probe.stdout)
        if Decimal(probe["format"]["duration"]) * 1000 < command.end_ms:
            raise ValueError("derivation selection exceeds parent media")
        video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
        target.mkdir(parents=True, exist_ok=True)
        staged = target / ".derived-video.mp4"
        if staged.exists():
            raise ValueError("preserved derivation staging artifact requires explicit resolution")
        argv = [FFMPEG, "-hide_banner", "-nostdin", "-i", str(parent / "video.mp4"),
                "-ss", str(Decimal(command.start_ms) / 1000), "-t", str(Decimal(command.end_ms - command.start_ms) / 1000),
                "-map", "0:v:0", "-map", "0:a?", "-sn", "-dn", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", "-n", str(staged)]
        # Exact derived range is a new media asset, not a rendering of an existing authority.
        # Audio is explicitly AAC for an exact sample-clock cut, and this command is retained in provenance.
        self.process(argv, check=True, timeout=1800)
        media_boundary, stream = probe_video_boundary(staged, self.process)
        if abs(media_boundary.duration_ms - (command.end_ms - command.start_ms)) > 50:
            raise ValueError("derived media duration differs from selection")
        pts = media_boundary.frame_timestamps_us
        if not pts or pts[0] > 50000:
            raise ValueError("derived media lacks valid actual frame origin")
        if (stream["width"], stream["height"]) != (video["width"], video["height"]):
            raise ValueError("derived media dimensions changed")
        audio_probe = self.process([FFPROBE, "-v", "error", "-select_streams", "a",
                                    "-show_entries", "stream=codec_name,start_time", "-of", "json", str(staged)], check=True)
        audio_streams = json.loads(audio_probe.stdout)["streams"]
        if not audio_streams or any(item["codec_name"] != "aac" or abs(Decimal(item["start_time"])) > Decimal("0.001") for item in audio_streams):
            raise ValueError("derived audio lacks a zero-based AAC presentation timeline")
        for item in input_evidence.values():
            verify_evidence(item)
        staged.replace(target / "video.mp4")
        video_evidence = evidence(target / "video.mp4")
        write_json(target / "media_boundary.json", media_boundary.to_dict())
        metadata = read_json(parent / "meta.json")
        metadata["asset_id"] = {"source": command.asset_id.source, "group": command.asset_id.group, "item": command.asset_id.item}
        metadata["media_derivation"] = self._identity(command)
        write_json(target / "meta.json", metadata)
        media_ref = MediaRef("direct_url", str(parent / "video.mp4"), {"derivation": self._identity(command)})
        write_json(target / "media_ref.json", media_ref.to_dict())
        write_json(target / "chapters.json", transcript.to_dict())
        (target / "transcript.txt").write_text("\n\n".join(f"{chapter.number}. {chapter.title}\n" + "\n".join(
            f"{paragraph.speaker_label + ': ' if paragraph.speaker_label else ''}{paragraph.text}" for paragraph in chapter.paragraphs)
            for chapter in transcript.chapters) + "\n", encoding="utf-8")
        now = datetime.now(UTC).isoformat()
        artifact = DownloadedArtifact(command.asset_id, media_ref.kind, media_ref.value, str(parent / "video.mp4"),
                                      str(target / "video.mp4"), "explicit-local-derivation", video_evidence.size_bytes, "sha256",
                                      video_evidence.sha256, "ffmpeg-media-derivation", self.process([FFMPEG, "-version"], check=True).stdout.splitlines()[0], now, "downloaded")
        write_json(target / "download_manifest.json", artifact.to_manifest_dict())
        manifest = StageManifestDTO("media_derivation", command.asset_id.value, input_evidence,
                                    {name: evidence(target / filename) for name, filename in self._output_names().items()},
                                    {"request": self._identity(command), "command": argv,
                                     "tool": artifact.downloader_version, "audio_codec": "aac",
                                     "duration_tolerance_ms": 50}, now,
                                    {"media_derivation_encoding_calls": 1, "writes": 8})
        write_json(manifest_path, manifest.to_dict())
        self.verify(command)
        return {"status": "succeeded", "manifest_path": str(manifest_path), "media_derivation_encoding_calls": 1, "writes": 8}
