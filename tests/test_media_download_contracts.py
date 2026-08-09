from __future__ import annotations

import json
from pathlib import Path

import pytest

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId
from infrastructure.infrastructure.process import ProcessResult
from media_download.application import (
    DownloadAssetVideoService,
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
    Sha256ChecksumCalculator,
    YtDlpDownloader,
)
import media_download.infrastructure.resolver as resolver_module


FIXTURES = Path(__file__).parent / "fixtures"


class StubHttpClient:
    def __init__(self, html: str) -> None:
        self.html = html
        self.urls: list[str] = []

    def get_text(self, url: str) -> str:
        self.urls.append(url)
        return self.html


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


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("page_url", "https://buffett.cnbc.com/video/example.html"),
        ("direct_url", "https://media.example/video.m3u8"),
        ("embed_id", "dQw4w9WgXcQ"),
    ],
)
def test_media_ref_from_dict_accepts_supported_kinds(kind: str, value: str) -> None:
    ref = MediaRef.from_dict({"kind": kind, "value": value})

    assert ref.kind == kind
    assert ref.value == value
    assert ref.extra == {}


@pytest.mark.parametrize(
    "data",
    [
        {"value": "https://example.com/video"},
        {"kind": "direct_url"},
        {"kind": "unsupported", "value": "https://example.com/video"},
        {"kind": "direct_url", "value": ""},
        {"kind": "direct_url", "value": "https://example.com/video", "extra": []},
    ],
)
def test_media_ref_from_dict_rejects_invalid_input(data: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        MediaRef.from_dict(data)


def test_media_ref_round_trips_extra() -> None:
    original = MediaRef.from_dict(
        {
            "kind": "embed_id",
            "value": "dQw4w9WgXcQ",
            "extra": {"video_id": "dQw4w9WgXcQ"},
        }
    )

    assert MediaRef.from_dict(original.to_dict()) == original


def test_media_ref_rejects_constructor_and_mapping_type_errors() -> None:
    with pytest.raises(ValueError):
        MediaRef("direct_url", "https://example.com/video", extra=[])
    with pytest.raises(ValueError):
        MediaRef.from_dict({"kind": 123, "value": "https://example.com/video"})
    with pytest.raises(ValueError):
        MediaRef.from_dict({"kind": "direct_url", "value": 123})


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


def test_resolver_registry_raises_when_no_resolver_accepts() -> None:
    registry = ResolverRegistry()

    with pytest.raises(ValueError):
        registry.select(_input(MediaRef("direct_url", "https://media.example/video.m3u8")))


def test_resolver_registry_keeps_specific_resolver_before_broad_match() -> None:
    input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    registry = ResolverRegistry()
    direct = DirectUrlResolver()
    broad = BroadResolver("https://broad.example/video.m3u8")
    registry.register(direct)
    registry.register(broad)

    assert registry.select(input) is direct
    assert registry.select(input).resolve(input) == input.media_ref.value


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


def test_cnbc_playback_url_preserves_absolute_url() -> None:
    from media_download.infrastructure import extract_cnbc_playback_url

    resolved = extract_cnbc_playback_url(
        r'{"playbackURL":"https:\/\/cdn.example.com\/video.m3u8"}',
        fallback_url="https://buffett.cnbc.com/video.html",
    )

    assert resolved == "https://cdn.example.com/video.m3u8"


def test_plan_skips_existing_output_unless_overwrite_is_explicit(tmp_path: Path) -> None:
    input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    service = _service(tmp_path, FakeResolver())
    workspace = build_asset_workspace(input.asset_id, tmp_path / "output")
    video_path = workspace / "video.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"existing")

    skipped = service.plan(input)
    overwrite = service.plan(input, DownloadPolicy(overwrite=True))

    assert skipped.action == DownloadAction.SKIP
    assert skipped.reason == "output already exists"
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


def test_execute_skip_without_manifest_does_not_create_artifact(tmp_path: Path) -> None:
    input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    service = _service(tmp_path, FakeResolver())
    workspace = build_asset_workspace(input.asset_id, tmp_path / "output")
    video_path = workspace / "video.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"existing")

    result = service.execute(input)

    assert result.plan.action == DownloadAction.SKIP
    assert result.artifact is None
    assert result.manifest_path is None


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


def test_yt_dlp_overwrite_uses_force_overwrites_without_continue() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(command, **kwargs):
        normalized = tuple(str(part) for part in command)
        calls.append(normalized)
        if normalized == ("yt-dlp", "--version"):
            return ProcessResult(normalized, 0, "2026.01.01\n", "")
        return ProcessResult(normalized, 0, "", "")

    plan = DownloadPlan(
        asset_id=_asset_id(),
        media_ref=MediaRef("direct_url", "https://media.example/video.m3u8"),
        media_url="https://media.example/video.m3u8",
        output_path="output/youtube_dqw4w9wgxcq/video.mp4",
        manifest_path="output/youtube_dqw4w9wgxcq/download_manifest.json",
        policy=DownloadPolicy(overwrite=True),
        action=DownloadAction.DOWNLOAD,
        reason="test",
    )

    YtDlpDownloader(process_runner=runner).download(plan)

    assert "--force-overwrites" in calls[0]
    assert "--continue" not in calls[0]


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


def test_execute_skip_rereads_existing_manifest_without_downloading(tmp_path: Path) -> None:
    input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    service = _service(tmp_path, FakeResolver())
    workspace = build_asset_workspace(input.asset_id, tmp_path / "output")
    video_path = workspace / "video.mp4"
    manifest_path = workspace / "download_manifest.json"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"existing")
    artifact = _artifact(tmp_path, output_path=str(video_path))
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


def test_yt_dlp_raises_when_primary_and_fallback_fail() -> None:
    from infrastructure.infrastructure.process import ProcessExecutionError

    def runner(command, **kwargs):
        normalized = tuple(str(part) for part in command)
        return ProcessResult(normalized, 1, "", "failed")

    plan = DownloadPlan(
        asset_id=_asset_id(),
        media_ref=MediaRef("direct_url", "https://media.example/video.m3u8"),
        media_url="https://media.example/video.m3u8",
        output_path="output/youtube_dqw4w9wgxcq/video.mp4",
        manifest_path="output/youtube_dqw4w9wgxcq/download_manifest.json",
        policy=DownloadPolicy(format_selector="bestvideo", fallback_format="best"),
        action=DownloadAction.DOWNLOAD,
        reason="test",
    )

    with pytest.raises(ProcessExecutionError):
        YtDlpDownloader(process_runner=runner).download(plan)


def test_yt_dlp_version_handles_dry_run_failure_and_empty_stdout() -> None:
    failures: list[tuple[str, ...]] = []

    def failing_runner(command, **kwargs):
        normalized = tuple(str(part) for part in command)
        failures.append(normalized)
        return ProcessResult(normalized, 1, "", "missing")

    def empty_runner(command, **kwargs):
        normalized = tuple(str(part) for part in command)
        return ProcessResult(normalized, 0, "", "")

    assert YtDlpDownloader(process_runner=failing_runner).version(dry_run=True) == "dry-run"
    assert failures == []
    assert YtDlpDownloader(process_runner=failing_runner).version() == "unknown"
    assert YtDlpDownloader(process_runner=empty_runner).version() == "unknown"


def test_domain_validators_reject_bad_policy_and_input() -> None:
    with pytest.raises(ValueError):
        DownloadPolicy(format_selector="")
    with pytest.raises(ValueError):
        DownloadPolicy(retries=-1)
    with pytest.raises(ValueError):
        DownloadPolicy(merge_output_format="")
    with pytest.raises(ValueError):
        DownloadInput("asset", MediaRef("direct_url", "https://example.com/video"))
    with pytest.raises(ValueError):
        DownloadInput(_asset_id(), "media-ref")


def _asset_id() -> AssetId:
    return AssetId("youtube", "", "dQw4w9WgXcQ")


def _input(media_ref: MediaRef) -> DownloadInput:
    return DownloadInput(_asset_id(), media_ref)


def _service(
    tmp_path: Path,
    resolver: FakeResolver,
    *,
    downloader=None,
) -> DownloadAssetVideoService:
    registry = ResolverRegistry()
    registry.register(resolver)
    return DownloadAssetVideoService(
        resolver_registry=registry,
        downloader=downloader or FakeDownloader(),
        checksum=Sha256ChecksumCalculator(),
        artifacts=LocalDownloadArtifactStore(),
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
