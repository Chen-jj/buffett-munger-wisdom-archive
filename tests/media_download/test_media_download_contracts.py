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


FIXTURES = Path(__file__).parents[1] / "fixtures"


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


def test_http_client_sends_headers_and_reuses_session(monkeypatch) -> None:
    session = _FakeMediaSession(_FakeMediaResponse(b"page html"))
    _install_fake_requests(monkeypatch, session)
    client = RequestsHttpClient(timeout=7.0, user_agent="media-agent/2")

    assert client.get_text("https://example.test/video") == "page html"
    assert client.get_text("https://example.test/other") == "page html"

    assert session.calls == [
        (
            "https://example.test/video",
            {"User-Agent": "media-agent/2"},
            7.0,
        ),
        (
            "https://example.test/other",
            {"User-Agent": "media-agent/2"},
            7.0,
        ),
    ]


def test_http_client_propagates_http_errors(monkeypatch) -> None:
    session = _FakeMediaSession(_FakeMediaResponse(b"", fail=True))
    _install_fake_requests(monkeypatch, session)

    with pytest.raises(RuntimeError, match="404"):
        RequestsHttpClient().get_text("https://example.test/missing")


def test_http_client_requires_requests_package(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "requests", None)

    with pytest.raises(RuntimeError, match="requests is required"):
        RequestsHttpClient().get_text("https://example.test/video")


@pytest.mark.parametrize(
    ("encoding", "apparent_encoding"),
    [
        ("ISO-8859-1", "utf-8"),
        (None, "utf-8"),
    ],
)
def test_http_client_decodes_utf8_pages_correctly(
    monkeypatch, encoding, apparent_encoding
) -> None:
    body = "playbackURL: \u2014/master.m3u8\n".encode("utf-8")
    session = _FakeMediaSession(
        _FakeMediaResponse(
            body, encoding=encoding, apparent_encoding=apparent_encoding
        )
    )
    _install_fake_requests(monkeypatch, session)

    text = RequestsHttpClient().get_text("https://buffett.cnbc.com/video")

    assert text == "playbackURL: \u2014/master.m3u8\n"


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








def test_cnbc_playback_url_preserves_absolute_url() -> None:
    from media_download.infrastructure import extract_cnbc_playback_url

    resolved = extract_cnbc_playback_url(
        r'{"playbackURL":"https:\/\/cdn.example.com\/video.m3u8"}',
        fallback_url="https://buffett.cnbc.com/video.html",
    )

    assert resolved == "https://cdn.example.com/video.m3u8"










@pytest.mark.parametrize(
    ("artifact_change", "category"),
    [
        ({"asset_id": AssetId("youtube", "", "other")}, "asset_mismatch"),
        (
            {"media_ref_value": "https://media.example/other.m3u8"},
            "media_ref_mismatch",
        ),
        ({"status": "failed"}, "status_not_successful"),
        ({"output_path": "output/other/video.mp4"}, "artifact_path_mismatch"),
        ({"size_bytes": 124}, "size_mismatch"),
        ({"checksum_algorithm": "md5"}, "checksum_algorithm_mismatch"),
        ({"checksum_value": "different"}, "checksum_mismatch"),
    ],
)
def test_plan_rejects_unverified_existing_artifact_with_stable_category(
    tmp_path: Path,
    artifact_change: dict[str, object],
    category: str,
) -> None:
    input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    output_path = str(
        build_asset_workspace(input.asset_id, tmp_path / "output") / "video.mp4"
    )
    manifest_path = str(Path(output_path).with_name("download_manifest.json"))
    artifact = replace(
        _artifact(tmp_path, output_path=output_path),
        **artifact_change,
    )
    artifacts = FakeArtifactStore()
    artifacts.present.update({output_path, manifest_path})
    artifacts.sizes[output_path] = 123
    artifacts.manifests[manifest_path] = artifact
    checksum = FakeChecksumCalculator({output_path: "abc123"})
    service = _service(
        tmp_path,
        FakeResolver(),
        artifacts=artifacts,
        checksum=checksum,
    )

    with pytest.raises(ExistingDownloadConflict) as error:
        service.plan(input)

    assert error.value.category == category


def test_plan_rejects_unreadable_existing_manifest(tmp_path: Path) -> None:
    input = _input(MediaRef("direct_url", "https://media.example/video.m3u8"))
    output_path = str(
        build_asset_workspace(input.asset_id, tmp_path / "output") / "video.mp4"
    )
    manifest_path = str(Path(output_path).with_name("download_manifest.json"))
    artifacts = FakeArtifactStore()
    artifacts.present.update({output_path, manifest_path})
    artifacts.manifests[manifest_path] = ValueError("corrupt manifest details")
    service = _service(
        tmp_path,
        FakeResolver(),
        artifacts=artifacts,
        checksum=FakeChecksumCalculator({}),
    )

    with pytest.raises(ExistingDownloadConflict) as error:
        service.plan(input)

    assert error.value.category == "manifest_invalid"
    assert "corrupt manifest details" not in str(error.value)










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
