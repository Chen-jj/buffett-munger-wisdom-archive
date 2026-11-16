"""Current workflow with real local evidence/checkpoint/store and fake provider."""

import hashlib
import json
from pathlib import Path

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId
from archive_core.interfaces.bilingual import ArtifactEvidenceDTO, StageManifestDTO
from tests.translation.chunk_support import source, output
from translation.domain import ProviderIdentity, ProviderResponse, ProviderStatus, PermanentProviderError
from translation.interfaces import TranslationCommand, build_translation_handler


def encoded(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(encoded(value))
    return ArtifactEvidenceDTO(str(path),path.stat().st_size,hashlib.sha256(path.read_bytes()).hexdigest())


class Provider:
    identity=ProviderIdentity("fake","fake",{"policy":"fixed"})
    def __init__(self):self.calls=[];self.fail_at=None
    def translate(self,call):
        self.calls.append(call)
        if len(self.calls)==self.fail_at:raise PermanentProviderError("secret",code="configuration")
        return ProviderResponse(ProviderStatus.COMPLETED,output(call.request),1)


class Clock:
    def now_utc(self):return "2026-11-05T00:00:00Z"


def prepared(tmp_path,count=3):
    alignment,chunks=source(count,sections=True)
    root=tmp_path/"output"
    workspace=build_asset_workspace(AssetId("synthetic","chunks","test"),root)
    src=write(workspace/"source_alignment.json",alignment.to_dict())
    chunks_data=chunks.to_dict();chunks_data["source_alignment_sha256"]=src.sha256
    video=workspace/"video.mp4";video.write_bytes(b"real-test-file-not-media")
    video_e=ArtifactEvidenceDTO(str(video),video.stat().st_size,hashlib.sha256(video.read_bytes()).hexdigest())
    chunks_data["media"]["video_sha256"]=video_e.sha256
    bound=write(workspace/"media_boundary.json",chunks_data["media"])
    trans=write(workspace/"transcription_manifest.json",{
        "schema_version":"transcription.audio-vad-asr-cache.v1",
        "asset":{"source":"synthetic","group":"chunks","item":"test"},
        "records":{"source_alignment":dict(src.to_dict(),status="succeeded",cache_key="fake",provenance={}),
                   "audio":{"provenance":{"video_sha256":video_e.sha256}}},
        "workflow":{"status":"succeeded"},
    })
    plan=write(workspace/"source_chunks.json",chunks_data)
    report=write(workspace/"source_chunking_report.json",{"status":"succeeded"})
    write(workspace/"source_chunking_manifest.json",StageManifestDTO("source_chunking","synthetic:chunks:test",
        {"transcription_manifest":trans,"source_alignment":src,"video":video_e,"media_boundary":bound},
        {"source_chunks":plan,"report":report},{"model":"fake"},"2026-11-05T00:00:00Z",{}).to_dict())
    provider=Provider()
    handler=build_translation_handler(output_root=str(root),provider=provider,clock=Clock())
    command=TranslationCommand("synthetic:chunks:test",str(workspace/"transcription_manifest.json"),str(workspace/"source_chunking_manifest.json"))
    return handler,command,provider,workspace


def snapshot(workspace):
    return {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in workspace.iterdir() if p.is_file()}
