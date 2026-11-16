"""Real local SRT artifact store and codec, with frozen current-schema inputs."""
from pathlib import Path
from srt_processing.interfaces.workflow import SrtProcessingCommand, build_srt_processing_handler
from tests.srt_processing.workflow_fakes import WorkflowCase


class LocalCase:
    def __init__(self, root):
        fake = WorkflowCase()
        self.root = Path(root).resolve()
        self.workspace = self.root / "cnbc_2000_sample"
        self.workspace.mkdir(parents=True)
        for path, raw in fake.upstream.items():
            if path.endswith(".json"):
                raw = raw.replace(fake.workspace.encode(), str(self.workspace).encode())
            (self.workspace / Path(path).name).write_bytes(raw)
        # Canonical input paths are part of signed JSON; build signatures at the local root.
        fake.root, fake.workspace = str(self.root), str(self.workspace)
        fake.store.files = {}
        from tests.support.current_bilingual import alignment, populate_current_chain
        fake.put("video.mp4", b"mock media")
        fake.put("source_alignment.json", alignment().to_dict())
        source = fake.path("source_alignment.json")
        fake.put("transcription_manifest.json", {"schema_version":"transcription.audio-vad-asr-cache.v1",
            "asset":{"source":"cnbc","group":"2000","item":"sample"},"workflow":{"status":"succeeded"},
            "records":{"source_alignment":{"status":"succeeded","path":source,"size_bytes":fake.store.size(source),
              "sha256":fake.store.sha256(source)},"audio":{"provenance":{"video_sha256":fake.store.sha256(fake.path("video.mp4"))}}}})
        self.draft = populate_current_chain(fake, export=False)
        for path, raw in fake.store.files.items():
            Path(path).write_bytes(raw)
        self.command = SrtProcessingCommand(fake.asset_id, fake.path("bilingual_postprocessing_manifest.json"))
        self.handler = build_srt_processing_handler(output_root=str(self.root))
        self.input_names = set(path.name for path in self.workspace.iterdir())

    def snapshot(self):
        return {path.name: (path.read_bytes(),path.stat().st_mtime_ns) for path in self.workspace.iterdir() if path.is_file()}
