"""Read-only two-party presentation of frozen sentence/cue comparison data.

No planner, subtitle renderer, upstream stage, or provider is imported or run.
All output files are exclusive creates in a previously nonexistent directory.
"""

import argparse
import copy
import hashlib
import html
import json
from pathlib import Path


SIDES = ("v3", "agent153")
EXPECTED_COUNTS = {"v3": 163, "agent153": 153}
ROW_KEYS = {"sentence_id", "source_english", "source_chinese", *SIDES}
CUE_KEYS = {
    "cue_id", "associated_sentence_ids", "start_ms", "end_ms", "duration_ms",
    "sentence_local_fragments",
}


def fingerprint(path):
    payload = path.read_bytes()
    stat = path.stat()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def project_rows(rows):
    projected = []
    for row in rows:
        item = {key: row[key] for key in ("sentence_id", "source_english", "source_chinese")}
        for side in SIDES:
            item[side] = []
            for entry in row[side]:
                cue = entry["full_shared_cue"]
                item[side].append({
                    "cue_id": entry["cue_id"],
                    "associated_sentence_ids": copy.deepcopy(entry["associated_sentence_ids"]),
                    "start_ms": cue["start_ms"],
                    "end_ms": cue["end_ms"],
                    "duration_ms": cue["end_ms"] - cue["start_ms"],
                    "sentence_local_fragments": copy.deepcopy(entry["sentence_local_fragments"]),
                })
        projected.append(item)
    return projected


def verify_projection(source, projected, *, sentence_count=97, cue_counts=None):
    expected_ids = [f"s{number}" for number in range(1, sentence_count + 1)]
    assert [row["sentence_id"] for row in source] == expected_ids
    assert [row["sentence_id"] for row in projected] == expected_ids
    unique = {side: {} for side in SIDES}
    associations = {side: {} for side in SIDES}
    entries = dict.fromkeys(SIDES, 0)
    fragments = dict.fromkeys(SIDES, 0)
    for original, row in zip(source, projected, strict=True):
        assert set(row) == ROW_KEYS
        for field in ("sentence_id", "source_english", "source_chinese"):
            assert row[field] == original[field]
        for side in SIDES:
            assert len(row[side]) == len(original[side])
            for before, after in zip(original[side], row[side], strict=True):
                assert set(after) == CUE_KEYS
                assert after["cue_id"] == before["cue_id"]
                assert after["associated_sentence_ids"] == before["associated_sentence_ids"]
                assert after["sentence_local_fragments"] == before["sentence_local_fragments"]
                for field in ("start_ms", "end_ms"):
                    assert after[field] == before["full_shared_cue"][field]
                assert after["duration_ms"] == after["end_ms"] - after["start_ms"]
                assert after["sentence_local_fragments"]
                for fragment in after["sentence_local_fragments"]:
                    assert fragment["sentence_id"] == row["sentence_id"]
                    start = fragment["chinese_start_offset"]
                    end = fragment["chinese_end_offset"]
                    assert fragment["chinese_text"] == row["source_chinese"][start:end]
                    fragments[side] += 1
                cue_id = after["cue_id"]
                identity = {key: after[key] for key in (
                    "associated_sentence_ids", "start_ms", "end_ms", "duration_ms")}
                if cue_id in unique[side]:
                    assert unique[side][cue_id] == identity
                unique[side][cue_id] = identity
                associations[side].setdefault(cue_id, []).append(row["sentence_id"])
                entries[side] += 1
    counts = {side: len(unique[side]) for side in SIDES}
    assert counts == (EXPECTED_COUNTS if cue_counts is None else cue_counts)
    for side in SIDES:
        for cue_id, identity in unique[side].items():
            assert associations[side][cue_id] == identity["associated_sentence_ids"]
    return {"sentence_count": len(projected), "unique_cue_counts": counts,
            "sentence_cue_association_counts": entries, "local_fragment_counts": fragments,
            "source_text_exact": True, "cue_ids_ranges_text_times_exact": True,
            "shared_cues_counted_once": True, "only_two_parties_no_audits_or_notes": True}


def timestamp(milliseconds):
    seconds, millis = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"


def readable_text(text):
    escaped = html.escape(text, quote=False).replace("\\", "\\\\")
    for char in ("*", "_", "`", "[", "]"):
        escaped = escaped.replace(char, "\\" + char)
    return escaped


def render_markdown(rows):
    lines = ["# 最新 v3 与 agent：97 句内容对照", "",
             "两方各自列 cue，不按列表位置强行配对；全局去重为最新 v3 163 cues、agent 参考 153 cues。",
             "整 cue 显示时间和时长沿用冻结结果，不重新切分或改时间。",
             "跨句共用 cue 在各句只列本句正文；本句源时间是词锚点范围，不是另一套显示时间。",
             "本文只做内容展示，不新增质量评价。", ""]
    labels = {"v3": "最新 v3（163 cues）", "agent153": "agent 参考（153 cues）"}
    for row in rows:
        lines.extend([f"## {row['sentence_id'].upper()}", "",
                      f"**源英文：** {readable_text(row['source_english'])}", "",
                      f"**源中文：** {readable_text(row['source_chinese'])}", ""])
        for side in SIDES:
            lines.extend([f"### {labels[side]} · 本句 {len(row[side])} 个 cue 关联", ""])
            for cue in row[side]:
                start, end = timestamp(cue["start_ms"]), timestamp(cue["end_ms"])
                duration = f"{cue['duration_ms'] / 1000:.3f}"
                lines.extend([f"**{cue['cue_id']}** · 整 cue 显示 `{start} → {end}` · {duration} 秒", ""])
                shared = len(cue["associated_sentence_ids"]) > 1
                if shared:
                    names = "、".join(sid.upper() for sid in cue["associated_sentence_ids"])
                    lines.extend([f"共用 {names}（同一个 cue，以下仅为本句片段）。", ""])
                for fragment in cue["sentence_local_fragments"]:
                    if shared:
                        first = timestamp(fragment["local_source_start_ms"])
                        last = timestamp(fragment["local_source_end_ms"])
                        lines.extend([f"本句源时间 `{first} → {last}`（非字幕显示时间）。", ""])
                    lines.extend([f"> **本句中文：** {readable_text(fragment['chinese_text'])}", ">",
                                  f"> **本句英文：** {readable_text(fragment['english_text'])}", ""])
    return "\n".join(lines)


def write_exclusive(path, content):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def create_two_way(source, output):
    if output.exists():
        raise FileExistsError(output)
    before = fingerprint(source)
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    projected = project_rows(rows)
    checks = verify_projection(rows, projected)
    jsonl = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in projected)
    markdown = render_markdown(projected)
    assert fingerprint(source) == before
    output.mkdir()
    write_exclusive(output / "two_way_sentences.jsonl", jsonl)
    write_exclusive(output / "all_97_sentences.md", markdown)
    readback = [json.loads(line) for line in (output / "two_way_sentences.jsonl").read_text().splitlines()]
    assert verify_projection(rows, readback) == checks
    assert (output / "all_97_sentences.md").read_text() == render_markdown(readback)
    after = fingerprint(source)
    assert after == before
    evidence = {"status": "passed", "checks": checks, "source_before": before,
                "source_after": after, "source_unchanged": True,
                "helper": fingerprint(Path(__file__)), "exclusive_new_directory": True,
                "outputs": {name: fingerprint(output / name) for name in (
                    "two_way_sentences.jsonl", "all_97_sentences.md")}}
    write_exclusive(output / "verification.json", json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    evidence = create_two_way(args.source, args.output)
    print(json.dumps({"status": evidence["status"], "output": str(args.output.resolve()),
                      **evidence["checks"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
