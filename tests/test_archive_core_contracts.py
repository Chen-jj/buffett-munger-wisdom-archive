from pathlib import Path

import pytest

from archive_core.application import (
    build_asset_workspace,
    build_session_workspace,
    parse_session_workspace,
)
from archive_core.domain import (
    ArtifactRef,
    ArtifactType,
    AssetId,
    SessionId,
    TimeRange,
    canonical_filename,
)
from archive_core.interfaces import ManifestDTO, ProvenanceDTO


@pytest.mark.parametrize(
    ("asset_id", "value"),
    [
        (AssetId("cnbc", "1994", "morning"), "cnbc:1994:morning"),
        (AssetId("youtube", "", "dQw4w9WgXcQ"), "youtube::dQw4w9WgXcQ"),
        (
            AssetId("generic", "www.example.com", "..."),
            "generic:www.example.com:...",
        ),
    ],
)
def test_asset_id_accepts_raw_non_path_identity_fields(
    asset_id: AssetId, value: str
) -> None:
    assert asset_id.value == value


@pytest.mark.parametrize(
    "args",
    [
        ("", "1994", "morning"),
        ("cnbc", "", ""),
        ("cnbc", "", "bad/item"),
        ("cnbc", "", "bad\\item"),
        ("cnbc", "bad\x00group", "item"),
        ("cnbc", "bad\ngroup", "item"),
    ],
)
def test_asset_id_rejects_empty_required_or_path_unsafe_fields(
    args: tuple[str, str, str]
) -> None:
    with pytest.raises(ValueError):
        AssetId(*args)


def test_build_asset_workspace_generates_cnbc_flat_path(tmp_path: Path) -> None:
    workspace = build_asset_workspace(
        AssetId("cnbc", "1994", "morning"), tmp_path
    )

    assert workspace == tmp_path / "cnbc_1994_morning"


def test_build_asset_workspace_collapses_empty_group_for_youtube(
    tmp_path: Path,
) -> None:
    workspace = build_asset_workspace(AssetId("youtube", "", "dQw4w9WgXcQ"), tmp_path)

    assert workspace == tmp_path / "youtube_dqw4w9wgxcq"
    assert "__" not in workspace.name


def test_build_asset_workspace_sanitizes_generic_dot_locator(
    tmp_path: Path,
) -> None:
    workspace = build_asset_workspace(
        AssetId("generic", "www.example.com", "..."), tmp_path
    )

    assert workspace.parent == tmp_path
    assert workspace.name.startswith("generic_www_example_com_")
    assert len(workspace.name.rsplit("_", 1)[1]) == 8
    assert "/" not in workspace.name
    assert "\\" not in workspace.name
    assert "." not in workspace.name
    assert workspace.name == workspace.name.lower()


def test_build_asset_workspace_truncates_long_generic_locator_with_hash(
    tmp_path: Path,
) -> None:
    long_item = "annual-meeting-" + ("segment-" * 20) + "final"

    workspace = build_asset_workspace(AssetId("generic", "long", long_item), tmp_path)

    assert workspace.parent == tmp_path
    assert workspace.name.startswith("generic_long_annual-meeting")
    assert len(workspace.name) == 100
    assert len(workspace.name.rsplit("_", 1)[1]) == 8


def test_build_asset_workspace_hash_prevents_long_name_collision(
    tmp_path: Path,
) -> None:
    prefix = "same-prefix-" + ("segment-" * 20)
    first = build_asset_workspace(AssetId("generic", "long", prefix + "a"), tmp_path)
    second = build_asset_workspace(AssetId("generic", "long", prefix + "b"), tmp_path)

    assert len(first.name) == 100
    assert len(second.name) == 100
    assert first != second


def test_session_id_and_deprecated_builder_remain_import_compatible() -> None:
    session_id = SessionId(year=1994, session="morning")

    assert session_id.value == "1994:morning"
    assert session_id.workspace_path == "output/cnbc_1994_morning"
    assert (
        build_session_workspace("/repo/output", session_id).workspace_path
        == "/repo/output/cnbc_1994_morning"
    )


def test_artifact_ref_uses_canonical_filenames_under_asset_workspace() -> None:
    asset_id = AssetId("cnbc", "1994", "morning")

    ref = ArtifactRef.canonical(asset_id, ArtifactType.RENDERED_VIDEO)

    assert canonical_filename(ArtifactType.TRANSCRIPT) == "transcript.txt"
    assert canonical_filename(ArtifactType.CHINESE_SRT) == "chinese.srt"
    assert ref.relative_path == "cnbc_1994_morning/video_\u4e2d\u6587\u5b57\u5e55.mp4"


def test_workspace_parser_round_trips_session_builder_output() -> None:
    built = build_session_workspace("/repo/output", SessionId(1994, "afternoon"))
    parsed = parse_session_workspace(built.workspace_path)

    assert parsed.session_id == SessionId(1994, "afternoon")
    assert parsed.workspace_path == built.workspace_path
    assert (
        parsed.artifact_path(ArtifactType.ENGLISH_SRT)
        == "/repo/output/cnbc_1994_afternoon/english.srt"
    )

    with pytest.raises(ValueError):
        parse_session_workspace("/repo/output/1994/afternoon")


def test_manifest_dto_round_trips_explicit_json_shape() -> None:
    asset_id = AssetId("cnbc", "1994", "morning")
    transcript = ArtifactRef.canonical(asset_id, ArtifactType.TRANSCRIPT)
    provenance = ProvenanceDTO(
        stage="crawl",
        tool="legacy-step0",
        input_artifacts=[],
        parameters={"source": "cnbc"},
    )

    manifest = ManifestDTO.from_domain(asset_id, [transcript], [provenance])
    data = manifest.to_dict()
    restored = ManifestDTO.from_dict(data)

    assert data["schema_version"] == "archive-core.manifest.v1"
    assert data["asset"] == {
        "id": "cnbc:1994:morning",
        "source": "cnbc",
        "group": "1994",
        "item": "morning",
    }
    assert data["artifacts"][0] == {
        "asset_id": "cnbc:1994:morning",
        "artifact_type": "transcript",
        "path": "cnbc_1994_morning/transcript.txt",
    }
    assert restored.to_dict() == data


def test_time_range_validates_monotonic_bounds() -> None:
    assert TimeRange(1.0, 1.5).end_seconds == 1.5

    with pytest.raises(ValueError):
        TimeRange(2.0, 1.0)
