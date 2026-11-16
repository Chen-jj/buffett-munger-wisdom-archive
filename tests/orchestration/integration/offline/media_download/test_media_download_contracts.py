from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import types

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId
from infrastructure.infrastructure.process import ProcessResult
from media_download.application import (
    DownloadAssetVideoService,
    ExistingDownloadConflict,
    ResolverRegistry,
)
from media_download.domain import (
    MANIFEST_SCHEMA,
    DownloadAction,
    DownloadInput,
    DownloadedArtifact,
    DownloadPlan,
    DownloadPolicy,
    MediaRef,
)
from media_download.infrastructure import (
    CnbcPlaybackUrlResolver,
    DirectUrlResolver,
    EmbedIdResolver,
    LocalDownloadArtifactStore,
    RequestsHttpClient,
    Sha256ChecksumCalculator,
    YtDlpDownloader,
)
import media_download.infrastructure.resolver as resolver_module


FIXTURES = Path(__file__).parents[4] / "fixtures"


class StubHttpClient:
    def __init__(self, html: str) -> None:
        self.html = html
        self.urls: list[str] = []

    def get_text(self, url: str) -> str:
        self.urls.append(url)
        return self.html


class _FakeMediaResponse:
    """Simulates requests' decoding: ``text`` decodes ``content`` with the
    current ``encoding``, so reassigning ``encoding`` changes the result."""

    def __init__(
        self,
        content: bytes,
        *,
        encoding: str | None = "utf-8",
        apparent_encoding: str = "utf-8",
        fail: bool = False,
    ) -> None:
        self.content = content
        self.encoding = encoding
        self.apparent_encoding = apparent_encoding
        self._fail = fail

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "utf-8")

    def raise_for_status(self) -> None:
        if self._fail:
            raise RuntimeError("404 Client Error")


class _FakeMediaSession:
    def __init__(self, response: _FakeMediaResponse) -> None:
        self._response = response
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def get(self, url: str, headers: dict[str, str], timeout: float):
        self.calls.append((url, dict(headers), timeout))
        return self._response


def _install_fake_requests(monkeypatch, session: _FakeMediaSession) -> None:
    module = types.ModuleType("requests")
    module.Session = lambda: session  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "requests", module)










class FakeResolver:
    def __init__(self, resolved_url: str = "https://media.example/video.m3u8") -> None:
        self.resolved_url = resolved_url
        self.inputs: list[DownloadInput] = []

    def accepts(self, input: DownloadInput) -> bool:
        return True

    def resolve(self, input: DownloadInput) -> str:
        self.inputs.append(input)
        return self.resolved_url


class BroadResolver(FakeResolver):
    pass


class FakeDownloader:
    def __init__(self, payload: bytes = b"downloaded video") -> None:
        self.payload = payload
        self.plans: list[DownloadPlan] = []

    def download(self, plan: DownloadPlan):
        self.plans.append(plan)
        Path(plan.output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(plan.output_path).write_bytes(self.payload)
        from media_download.domain import DownloaderResult

        return DownloaderResult(
            downloader_name="fake-dlp",
            downloader_version="1.0",
            command=("fake-dlp", plan.media_url),
            format_selector=plan.policy.format_selector,
        )


class FakeChecksumCalculator:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values
        self.paths: list[str] = []

    def sha256(self, path: str) -> str:
        self.paths.append(path)
        return self.values[path]


class FakeArtifactStore:
    def __init__(self) -> None:
        self.present: set[str] = set()
        self.sizes: dict[str, int] = {}
        self.manifests: dict[str, DownloadedArtifact | Exception] = {}

    def exists(self, path: str) -> bool:
        return path in self.present

    def size(self, path: str) -> int:
        return self.sizes[path]

    def write_manifest(self, path: str, artifact: DownloadedArtifact) -> str:
        self.present.add(path)
        self.manifests[path] = artifact
        return path

    def read_manifest(self, path: str) -> DownloadedArtifact:
        stored = self.manifests[path]
        if isinstance(stored, Exception):
            raise stored
        return stored

    def read_media_ref(self, path: str) -> MediaRef:
        raise AssertionError("read_media_ref is not expected in this test")










def test_resolver_registry_dispatches_supported_media_refs() -> None:
    direct_input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    embed_input = _input(MediaRef("embed_id", "dQw4w9WgXcQ"))
    page_input = _input(MediaRef("page_url", "https://buffett.cnbc.com/video.html"))
    cnbc = CnbcPlaybackUrlResolver(
        http_client=StubHttpClient(
            FIXTURES.joinpath("media_download_cnbc_video.html").read_text(
                encoding="utf-8"
            )
        )
    )
    registry = ResolverRegistry()
    registry.register(DirectUrlResolver())
    registry.register(EmbedIdResolver())
    registry.register(cnbc)

    assert registry.select(direct_input).resolve(direct_input) == direct_input.media_ref.value
    assert (
        registry.select(embed_input).resolve(embed_input)
        == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )
    assert registry.select(page_input) is cnbc


def test_default_resolver_registry_orders_specialized_resolvers_first() -> None:
    registry = resolver_module.build_default_resolver_registry()
    direct_input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    embed_input = _input(MediaRef("embed_id", "dQw4w9WgXcQ"))
    page_input = _input(MediaRef("page_url", "https://buffett.cnbc.com/video.html"))

    assert isinstance(registry.select(direct_input), DirectUrlResolver)
    assert isinstance(registry.select(embed_input), EmbedIdResolver)
    assert isinstance(registry.select(page_input), CnbcPlaybackUrlResolver)






def test_cnbc_page_url_resolver_extracts_playback_url_offline() -> None:
    html = FIXTURES.joinpath("media_download_cnbc_video.html").read_text(
        encoding="utf-8"
    )
    http = StubHttpClient(html)
    input = _input(MediaRef("page_url", "https://buffett.cnbc.com/video.html"))
    resolver = CnbcPlaybackUrlResolver(http_client=http)

    resolved = resolver.resolve(input)

    assert resolved == "https://cdn.example.com/cnbc/video.m3u8"
    assert http.urls == ["https://buffett.cnbc.com/video.html"]


def test_cnbc_page_url_resolver_falls_back_when_playback_url_missing() -> None:
    html = FIXTURES.joinpath(
        "media_download_cnbc_video_without_playback.html"
    ).read_text(encoding="utf-8")
    input = _input(MediaRef("page_url", "https://buffett.cnbc.com/video.html"))

    resolved = CnbcPlaybackUrlResolver(http_client=StubHttpClient(html)).resolve(input)

    assert resolved == "https://buffett.cnbc.com/video.html"


def test_cnbc_resolver_creates_default_http_client_lazily(monkeypatch) -> None:
    html = FIXTURES.joinpath("media_download_cnbc_video.html").read_text(
        encoding="utf-8"
    )
    stub = StubHttpClient(html)
    monkeypatch.setattr(resolver_module, "RequestsHttpClient", lambda: stub)
    input = _input(MediaRef("page_url", "https://buffett.cnbc.com/video.html"))

    resolved = CnbcPlaybackUrlResolver().resolve(input)

    assert resolved == "https://cdn.example.com/cnbc/video.m3u8"




def test_plan_skips_only_when_existing_output_is_verified(tmp_path: Path) -> None:
    input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    service = _service(tmp_path, FakeResolver())
    workspace = build_asset_workspace(input.asset_id, tmp_path / "output")
    video_path = workspace / "video.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"existing")
    artifact = _valid_existing_artifact(input, video_path)
    LocalDownloadArtifactStore().write_manifest(
        str(workspace / "download_manifest.json"), artifact
    )

    skipped = service.plan(input)
    overwrite = service.plan(input, DownloadPolicy(overwrite=True))

    assert skipped.action == DownloadAction.SKIP
    assert skipped.reason == "existing output verified"
    assert skipped.media_url == artifact.media_url
    assert overwrite.action == DownloadAction.DOWNLOAD


def test_dry_run_execute_does_not_download_or_write_manifest(tmp_path: Path) -> None:
    input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    downloader = FakeDownloader()
    service = _service(tmp_path, FakeResolver(), downloader=downloader)

    result = service.execute(input, DownloadPolicy(dry_run=True))

    assert result.plan.action == DownloadAction.DOWNLOAD
    assert result.plan.reason == "dry-run"
    assert result.artifact is None
    assert result.manifest_path is None
    assert downloader.plans == []
    assert not Path(result.plan.output_path).exists()
    assert result.plan.should_download is False


def test_plan_paths_stay_inside_asset_workspace(tmp_path: Path) -> None:
    input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    service = _service(tmp_path, FakeResolver())

    plan = service.plan(input)

    workspace = build_asset_workspace(input.asset_id, tmp_path / "output")
    assert Path(plan.output_path) == workspace / "video.mp4"
    assert Path(plan.manifest_path) == workspace / "download_manifest.json"
    assert plan.should_download is True


def test_existing_output_without_manifest_is_a_conflict_and_is_preserved(
    tmp_path: Path,
) -> None:
    input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    downloader = FakeDownloader()
    service = _service(tmp_path, FakeResolver(), downloader=downloader)
    workspace = build_asset_workspace(input.asset_id, tmp_path / "output")
    video_path = workspace / "video.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"existing")

    with pytest.raises(ExistingDownloadConflict) as error:
        service.execute(input)

    assert error.value.category == "manifest_missing"
    assert video_path.read_bytes() == b"existing"
    assert downloader.plans == []






def test_checksum_mismatch_preserves_existing_output(tmp_path: Path) -> None:
    input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    downloader = FakeDownloader()
    service = _service(tmp_path, FakeResolver(), downloader=downloader)
    workspace = build_asset_workspace(input.asset_id, tmp_path / "output")
    video_path = workspace / "video.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"existing")
    artifact = replace(
        _valid_existing_artifact(input, video_path),
        checksum_value="different",
    )
    LocalDownloadArtifactStore().write_manifest(
        str(workspace / "download_manifest.json"), artifact
    )

    with pytest.raises(ExistingDownloadConflict) as error:
        service.execute(input)

    assert error.value.category == "checksum_mismatch"
    assert video_path.read_bytes() == b"existing"
    assert downloader.plans == []


def test_explicit_overwrite_replaces_unverified_existing_output(tmp_path: Path) -> None:
    input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    downloader = FakeDownloader(payload=b"replacement")
    service = _service(tmp_path, FakeResolver(), downloader=downloader)
    workspace = build_asset_workspace(input.asset_id, tmp_path / "output")
    video_path = workspace / "video.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"existing")

    result = service.execute(input, DownloadPolicy(overwrite=True))

    assert result.plan.action == DownloadAction.DOWNLOAD
    assert video_path.read_bytes() == b"replacement"
    assert len(downloader.plans) == 1


def test_stale_manifest_without_video_does_not_block_download(tmp_path: Path) -> None:
    input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    service = _service(tmp_path, FakeResolver())
    workspace = build_asset_workspace(input.asset_id, tmp_path / "output")
    manifest_path = workspace / "download_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("not valid json", encoding="utf-8")

    result = service.execute(input)

    assert result.plan.action == DownloadAction.DOWNLOAD
    assert result.artifact is not None
    assert (workspace / "video.mp4").exists()
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["download"][
        "status"
    ] == "downloaded"


def test_execute_with_yt_dlp_runner_retries_fallback_and_writes_manifest(
    tmp_path: Path,
) -> None:
    input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    calls: list[tuple[str, ...]] = []

    def runner(command, **kwargs):
        normalized = tuple(str(part) for part in command)
        calls.append(normalized)
        if normalized == ("yt-dlp", "--version"):
            return ProcessResult(normalized, 0, "2026.01.01\n", "")
        if normalized[normalized.index("-f") + 1] == "best":
            output_path = Path(normalized[normalized.index("-o") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"downloaded by runner")
            return ProcessResult(normalized, 0, "", "")
        return ProcessResult(normalized, 1, "", "primary failed")

    downloader = YtDlpDownloader(process_runner=runner)
    service = _service(tmp_path, FakeResolver(input.media_ref.value), downloader=downloader)
    policy = DownloadPolicy(
        format_selector="bestvideo",
        fallback_format="best",
        retries=5,
        rate_limit="1M",
    )

    result = service.execute(input, policy)

    assert result.artifact is not None
    assert calls[0][calls[0].index("-f") + 1] == "bestvideo"
    assert calls[1][calls[1].index("-f") + 1] == "best"
    assert calls[1][calls[1].index("--merge-output-format") + 1] == "mp4"
    assert calls[1][calls[1].index("--retries") + 1] == "5"
    assert "--continue" in calls[1]
    assert "--force-overwrites" not in calls[1]
    assert calls[1][calls[1].index("--limit-rate") + 1] == "1M"
    assert calls[1][calls[1].index("-o") + 1] == result.plan.output_path
    assert calls[1][-1].endswith("video.m3u8")
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == MANIFEST_SCHEMA
    assert Path(manifest["artifact"]["path"]).parent == build_asset_workspace(
        input.asset_id,
        tmp_path / "output",
    )




def test_manifest_round_trip_and_schema_rejection(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)
    store = LocalDownloadArtifactStore()
    manifest_path = tmp_path / "download_manifest.json"

    store.write_manifest(str(manifest_path), artifact)
    restored = store.read_manifest(str(manifest_path))

    assert restored == artifact
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["schema_version"] = "unknown-schema"
    with pytest.raises(ValueError, match="unrecognized manifest schema"):
        DownloadedArtifact.from_manifest_dict(data)


def test_execute_skip_returns_verified_manifest_without_downloading(tmp_path: Path) -> None:
    input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    service = _service(tmp_path, FakeResolver())
    workspace = build_asset_workspace(input.asset_id, tmp_path / "output")
    video_path = workspace / "video.mp4"
    manifest_path = workspace / "download_manifest.json"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"existing")
    artifact = _valid_existing_artifact(input, video_path)
    LocalDownloadArtifactStore().write_manifest(str(manifest_path), artifact)
    downloader = FakeDownloader()
    service = _service(tmp_path, FakeResolver(), downloader=downloader)

    result = service.execute(input)

    assert result.plan.action == DownloadAction.SKIP
    assert result.artifact == artifact
    assert result.manifest_path == str(manifest_path)
    assert downloader.plans == []


def test_service_builds_input_from_asset_media_ref(tmp_path: Path) -> None:
    asset_id = _asset_id()
    workspace = build_asset_workspace(asset_id, tmp_path / "output")
    workspace.mkdir(parents=True)
    (workspace / "media_ref.json").write_text(
        json.dumps({"kind": "embed_id", "value": "dQw4w9WgXcQ"}),
        encoding="utf-8",
    )
    service = _service(tmp_path, FakeResolver())

    input = service.build_input(asset_id)

    assert input == DownloadInput(asset_id, MediaRef("embed_id", "dQw4w9WgXcQ"))


def test_service_asset_shortcuts_read_media_ref(tmp_path: Path) -> None:
    asset_id = _asset_id()
    workspace = build_asset_workspace(asset_id, tmp_path / "output")
    workspace.mkdir(parents=True)
    (workspace / "media_ref.json").write_text(
        json.dumps({"kind": "direct_url", "value": "https://media.example/video.m3u8"}),
        encoding="utf-8",
    )
    service = _service(tmp_path, FakeResolver("https://media.example/video.m3u8"))

    plan = service.plan_asset(asset_id)
    result = service.execute_asset(asset_id, DownloadPolicy(dry_run=True))

    assert plan.media_ref.kind == "direct_url"
    assert result.plan.media_ref.value == "https://media.example/video.m3u8"








def _asset_id() -> AssetId:
    return AssetId("youtube", "", "dQw4w9WgXcQ")


def _input(media_ref: MediaRef) -> DownloadInput:
    return DownloadInput(_asset_id(), media_ref)


def _service(
    tmp_path: Path,
    resolver: FakeResolver,
    *,
    downloader=None,
    checksum=None,
    artifacts=None,
) -> DownloadAssetVideoService:
    registry = ResolverRegistry()
    registry.register(resolver)
    return DownloadAssetVideoService(
        resolver_registry=registry,
        downloader=downloader or FakeDownloader(),
        checksum=checksum or Sha256ChecksumCalculator(),
        artifacts=artifacts or LocalDownloadArtifactStore(),
        output_root=str(tmp_path / "output"),
    )


def _artifact(tmp_path: Path, *, output_path: str | None = None) -> DownloadedArtifact:
    return DownloadedArtifact(
        asset_id=_asset_id(),
        media_kind="direct_url",
        media_ref_value="https://media.example/video.m3u8",
        media_url="https://media.example/video.m3u8",
        output_path=output_path or str(tmp_path / "output" / "youtube_dqw4w9wgxcq" / "video.mp4"),
        format_selector="best",
        size_bytes=123,
        checksum_algorithm="sha256",
        checksum_value="abc123",
        downloader_name="yt-dlp",
        downloader_version="2026.01.01",
        downloaded_at="2026-07-26T00:00:00+00:00",
        status="downloaded",
    )


def _valid_existing_artifact(
    input: DownloadInput,
    video_path: Path,
) -> DownloadedArtifact:
    payload = video_path.read_bytes()
    return DownloadedArtifact(
        asset_id=input.asset_id,
        media_kind=input.media_ref.kind,
        media_ref_value=input.media_ref.value,
        media_url="https://media.example/resolved-video.m3u8",
        output_path=str(video_path),
        format_selector="best",
        size_bytes=len(payload),
        checksum_algorithm="sha256",
        checksum_value=hashlib.sha256(payload).hexdigest(),
        downloader_name="yt-dlp",
        downloader_version="2026.01.01",
        downloaded_at="2026-07-26T00:00:00+00:00",
        status="downloaded",
    )
