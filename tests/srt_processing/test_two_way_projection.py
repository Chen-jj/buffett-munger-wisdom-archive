import copy
import json
import re

import pytest

from tests.srt_processing import two_way_projection as projection


def make_entry(row, cue_id, left=0, right=None):
    number = int(row["sentence_id"][1:])
    text = row["source_chinese"]
    right = len(text) if right is None else right
    fragment = {"sentence_id": row["sentence_id"], "first_word_id": f"w{number}",
                "last_word_id": f"w{number}", "chinese_start_offset": left,
                "chinese_end_offset": right, "chinese_text": text[left:right],
                "english_text": row["source_english"], "speaker_label": None,
                "local_source_start_ms": number * 1000 + left * 10,
                "local_source_end_ms": number * 1000 + right * 10}
    return {"cue_id": cue_id, "associated_sentence_ids": [row["sentence_id"]],
            "sentence_local_fragments": [fragment],
            "full_shared_cue": {"start_ms": number * 1000 + left * 10,
                                "end_ms": number * 1000 + right * 10 + 7,
                                "english_text": "FULL CUE MUST NOT LEAK",
                                "reason": "OLD EVALUATION MUST NOT LEAK"},
            "v3_fixed_cut_audit": {"OLD AUDIT MUST NOT LEAK": True}}


@pytest.fixture
def source_rows():
    rows = [{"sentence_id": f"s{n}", "source_english": f"Sentence {n}.",
             "source_chinese": f"第{n}句。", "v1_242": ["OLD VERSION MUST NOT LEAK"]}
            for n in range(1, 98)]
    extras = {"v3": 64, "agent153": 55}
    for row in rows:
        n = int(row["sentence_id"][1:])
        for side in projection.SIDES:
            count = 1
            if n == 4 and side == "agent153":
                count = 2
            elif n == 17:
                count = 3 if side == "v3" else 2
            elif n not in (4, 19, 20) and extras[side]:
                count = 2
                extras[side] -= 1
            offsets = [0, *range(1, count), len(row["source_chinese"])]
            row[side] = [make_entry(row, f"{side}-{n}-{i}", left, right)
                         for i, (left, right) in enumerate(zip(offsets, offsets[1:]))]
    for n in (19, 20):
        entry = rows[n - 1]["agent153"][0]
        entry["cue_id"] = "a36"
        entry["associated_sentence_ids"] = ["s19", "s20"]
        entry["full_shared_cue"]["start_ms"] = 19000
        entry["full_shared_cue"]["end_ms"] = 20900
    return rows


def test_projection_preserves_all_fragments_and_independent_cue_counts(source_rows):
    before = copy.deepcopy(source_rows)
    rows = projection.project_rows(source_rows)
    checks = projection.verify_projection(source_rows, rows)
    assert source_rows == before
    assert checks["sentence_count"] == 97
    assert checks["unique_cue_counts"] == {"v3": 163, "agent153": 153}
    assert (len(rows[3]["v3"]), len(rows[3]["agent153"])) == (1, 2)
    assert (len(rows[16]["v3"]), len(rows[16]["agent153"])) == (3, 2)
    assert set(rows[0]) == projection.ROW_KEYS
    rows[0]["v3"][0]["sentence_local_fragments"][0]["chinese_text"] = "changed"
    assert source_rows == before


def test_s19_shared_cue_shows_only_local_text_and_distinct_source_time(source_rows):
    rows = projection.project_rows(source_rows)
    markdown = projection.render_markdown(rows)
    s19 = markdown.split("## S19\n", 1)[1].split("## S20\n", 1)[0]
    assert "共用 S19、S20" in s19
    assert "整 cue 显示 `00:00:19.000 → 00:00:20.900` · 1.900 秒" in s19
    assert "本句源时间 `00:00:19.000 → 00:00:19.050`（非字幕显示时间）" in s19
    assert "Sentence 19." in s19 and "第19句。" in s19
    assert "Sentence 18." not in s19 and "第18句。" not in s19
    assert "Sentence 20." not in s19 and "第20句。" not in s19
    assert "FULL CUE" not in markdown and "OLD" not in markdown


@pytest.mark.parametrize("change", ["text", "range", "time", "old_version", "duplicate_sentence"])
def test_verifier_rejects_changed_content_or_old_fields(source_rows, change):
    rows = projection.project_rows(source_rows)
    fragment = rows[0]["v3"][0]["sentence_local_fragments"][0]
    if change == "text":
        fragment["english_text"] += "changed"
    elif change == "range":
        fragment["chinese_end_offset"] += 1
    elif change == "time":
        rows[0]["agent153"][0]["end_ms"] += 1
    elif change == "old_version":
        rows[0]["v1_242"] = []
    else:
        rows[1]["sentence_id"] = "s1"
    with pytest.raises(AssertionError):
        projection.verify_projection(source_rows, rows)


def test_exclusive_generation_source_unchanged_and_repeatable(source_rows, tmp_path):
    source = tmp_path / "source.jsonl"
    projection.write_exclusive(source, "".join(json.dumps(row) + "\n" for row in source_rows))
    source_before = projection.fingerprint(source)
    first, second = tmp_path / "first", tmp_path / "second"
    evidence = projection.create_two_way(source, first)
    assert evidence["status"] == "passed" and evidence["source_unchanged"]
    assert source_before == projection.fingerprint(source)
    markdown = (first / "all_97_sentences.md").read_text()
    assert re.findall(r"^## S([0-9]+)$", markdown, re.MULTILINE) == [str(n) for n in range(1, 98)]
    assert markdown.count("**源英文：**") == markdown.count("**源中文：**") == 97
    assert "OLD" not in (first / "two_way_sentences.jsonl").read_text()
    snapshots = {path.name: projection.fingerprint(path) for path in first.iterdir()}
    with pytest.raises(FileExistsError):
        projection.create_two_way(source, first)
    assert snapshots == {path.name: projection.fingerprint(path) for path in first.iterdir()}
    projection.create_two_way(source, second)
    for name in ("all_97_sentences.md", "two_way_sentences.jsonl"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_invalid_source_does_not_create_output(tmp_path):
    source = tmp_path / "invalid.jsonl"
    projection.write_exclusive(source, "")
    output = tmp_path / "not_created"
    with pytest.raises(AssertionError):
        projection.create_two_way(source, output)
    assert not output.exists()
