"""Independent experiment guards and human-label contracts; synthetic inputs only."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import importlib
import json
import sys

import pytest

from archive_core.interfaces.bilingual import MediaBoundaryDTO
from tests.orchestration.integration.runners import chunking_evaluation as runner
from tests.support.current_bilingual import alignment


def labels_fixture():
    source = {"words": [{"id": f"w{n}"} for n in range(1, 7)],
              "sentences": [{"id": "s1", "first_word_id": "w1", "last_word_id": "w4"},
                            {"id": "s2", "first_word_id": "w5", "last_word_id": "w6"}]}
    labels = {"schema_version": "chunking.human-labels.v1", "items": [
        {"id": "synthetic-case", "sentence_id": "s1", "word_ids": ["w2", "w3"], "data_origin": "synthetic",
         "decision": "reject", "layer": "source_chunking", "forbidden_boundaries": [["w2", "w3"]],
         "allowed_groupings": [[["w1", "w2"], ["w3", "w4"]]], "allowed_boundaries": [["w3", "w4"]]}]}
    return source, labels


def test_label_schema_accepts_multiple_complete_canonical_witnesses():
    source, labels = labels_fixture()
    labels["items"][0]["allowed_groupings"].append([["w1", "w1"], ["w2", "w4"]])
    assert runner.validate_labels(labels, source) == labels


@pytest.mark.parametrize("fault", ("unknown_word", "unknown_sentence", "cross_sentence_word", "gap", "overlap", "reversed",
                                   "missing_tail", "empty_grouping", "unknown_nested_word", "nonadjacent_boundary", "cross_sentence_boundary",
                                   "unknown_range", "unknown_decision", "unknown_layer"))
def test_nested_human_labels_reject_unknown_ids_or_incomplete_ranges(fault):
    source, labels = labels_fixture()
    item = labels["items"][0]
    if fault == "unknown_word": item["word_ids"] = ["w999"]
    elif fault == "unknown_sentence": item["sentence_id"] = "s999"
    elif fault == "cross_sentence_word": item["word_ids"] = ["w5"]
    elif fault == "gap": item["allowed_groupings"] = [[["w1", "w1"], ["w3", "w4"]]]
    elif fault == "overlap": item["allowed_groupings"] = [[["w1", "w2"], ["w2", "w4"]]]
    elif fault == "reversed": item["allowed_groupings"] = [[["w1", "w2"], ["w4", "w3"]]]
    elif fault == "missing_tail": item["allowed_groupings"] = [[["w1", "w2"]]]
    elif fault == "empty_grouping": item["allowed_groupings"] = [[]]
    elif fault == "unknown_nested_word": item["allowed_groupings"] = [[["w1", "w999"]]]
    elif fault == "nonadjacent_boundary": item["forbidden_boundaries"] = [["w1", "w3"]]
    elif fault == "cross_sentence_boundary": item["forbidden_boundaries"] = [["w4", "w5"]]
    elif fault == "unknown_range": item["forbidden_cue_start_ranges"] = [["w1", "w999"]]
    elif fault == "unknown_decision": item["decision"] = "automatic-pass"
    else: item["layer"] = "guessed-acoustics"
    with pytest.raises(ValueError):
        runner.validate_labels(labels, source)


def test_observations_use_frozen_human_constraints_and_exclude_final_layer():
    source, labels = labels_fixture()
    final = deepcopy(labels["items"][0])
    final.update(id="synthetic-final-only", layer="final_bilingual")
    labels["items"].append(final)
    plan = {"chunks": [{"word_ids": ["w1", "w2"], "sentence_ids": ["s1"]},
                       {"word_ids": ["w3", "w4"], "sentence_ids": ["s1"]},
                       {"word_ids": ["w5", "w6"], "sentence_ids": ["s2"]}]}
    result = runner.label_observations(plan, labels, source)
    assert result[0]["known_constraint_violation"] is True
    assert result[0]["matched_acceptable_witness"] is True  # Independent channels can conflict; do not hide that.
    assert result[1]["excluded_from_source_pass_fail"] is True
    assert result[1]["assessment"] == "final-stage-review-required"


@pytest.mark.parametrize("capacity", (80, 84))
@pytest.mark.parametrize("use_gap", (True, False))
@pytest.mark.parametrize("pts_present", (True, False))
@pytest.mark.parametrize("objective", ("production", "B", "U", "S", "US"))
def test_isolated_capacity_override_binds_real_policy_and_measured_capacity_issue(tmp_path, monkeypatch, capsys, capacity, use_gap, pts_present, objective):
    # One unbreakable synthetic 81-character word proves policy and metrics agree.
    source = alignment(sections=False)
    text = "x" * 81
    word = replace(source.words[0], text=text)
    sentence = replace(source.sentences[0], first_word_id=word.id, last_word_id=word.id,
                       start_ms=word.start_ms, end_ms=word.end_ms, text=text)
    source = replace(source, words=(word,), sentences=(sentence,))
    source_path, media_path, cache_path = (tmp_path / name for name in ("source.json", "media.json", "cache.json"))
    runner.write_exclusive(source_path, source.to_dict())
    runner.write_exclusive(media_path, MediaBoundaryDTO("a" * 64, 3000,
        tuple(range(0, 3000000, 40000)) if pts_present else None).to_dict())
    identity = {"engine": "synthetic", "model_manifest_sha256": "b" * 64}
    runner.write_exclusive(cache_path, {"analyzer_identity": identity, "rows": [{"word_ids": [word.id], "sentences": [{
        "tokens": [{"text": text, "start_char": 0, "end_char": len(text), "words": [{"text": text, "xpos": "NN"}]}],
        "constituency": f"(ROOT (S (NP (NN {text}))))"}]}]})
    import srt_processing.infrastructure.stanza_chunking as stanza_adapter
    monkeypatch.setattr(stanza_adapter, "StanzaConstituencyAnalyzer", lambda _: SimpleNamespace(identity=identity))
    chunking = importlib.import_module("srt_processing.domain.chunking")
    policy = importlib.import_module("srt_processing.domain.chunking_policy")
    actual_fields = tuple(getattr(policy, "SCORE_FIELDS", runner._OBJECTIVE_FIELDS))
    actual_grade = chunking._ordinary_grade
    production_default_grade = actual_grade({"ordinary"})
    actual_cost = chunking._PartitionScorer.cost
    actual_policy = policy.chunking_policy()
    monkeypatch.setattr(chunking, "ENGLISH_MAX_CHARACTERS", chunking.ENGLISH_MAX_CHARACTERS)
    monkeypatch.setattr(policy, "ENGLISH_MAX_CHARACTERS", policy.ENGLISH_MAX_CHARACTERS)
    monkeypatch.setattr(chunking, "_split_sentence", chunking._split_sentence)
    monkeypatch.setattr(chunking, "_PartitionScorer", chunking._PartitionScorer)
    monkeypatch.setattr(chunking._PartitionScorer, "cost", chunking._PartitionScorer.cost)
    monkeypatch.setattr(chunking, "_ordinary_grade", chunking._ordinary_grade)
    if objective != "production":
        # A synthetic historical worker fixture, never a production legacy route.
        def historical_cost(self, *args, **kwargs):
            cost = actual_cost(self, *args, **kwargs)
            return tuple(cost[actual_fields.index(name)] for name in runner._OBJECTIVE_FIELDS)
        def historical_grade(relations):
            return 3 if set(relations) == {"ordinary"} else actual_grade(relations)
        def historical_policy():
            result = deepcopy(actual_policy)
            result.update(version="english-typed-cue-dp.v3", english_max_characters=policy.ENGLISH_MAX_CHARACTERS,
                          boundary_ranking="synthetic-frozen-cps-before-syntax", ordinary_default_grade=3)
            result.pop("score_fields", None)
            return result
        monkeypatch.setattr(chunking._PartitionScorer, "cost", historical_cost)
        monkeypatch.setattr(chunking, "_ordinary_grade", historical_grade)
        monkeypatch.setattr(policy, "chunking_policy", historical_policy)
        monkeypatch.setattr(chunking, "chunking_policy", historical_policy)
        monkeypatch.setattr(policy, "SCORE_FIELDS", None, raising=False)
    monkeypatch.setattr(sys, "argv", ["synthetic-worker", str(source_path), str(media_path), str(cache_path), "no-real-model", str(capacity),
                                     json.dumps({"use_gap": use_gap}), objective])
    exec(runner._EVALUATION_WORKER, {"__name__": "__main__"})
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["plan"]["policy"]["english_max_characters"] == capacity
    assert result["metrics"][0]["characters"] == 81
    assert ("english.capacity" in result["metrics"][0]["issues"]) is (capacity == 80)
    trace = result["trace"]
    assert trace["sentence_count"] == 1
    assert trace["final_groups_after_short_rescue"] == [[word.id]]
    assert trace["sentences"][0]["relative_gap_statistics"]["availability_reason"] == (
        "insufficient_samples" if pts_present else "missing_pts")
    assert trace["sentences"][0]["relative_gap_statistics"]["scoring_enabled"] is use_gap
    assert trace["sentences"][0]["relative_gap_statistics"]["scoring_applicable"] is False
    assert trace["sentences"][0]["actual_stanza_triggered"] is (capacity == 80)
    assert trace["actual_global_rescue_score_final"]["components"]["cue_count"] == 1
    expected_order = list(runner._OBJECTIVE_ORDER) if objective in {"S", "US"} else list(range(13))
    assert result["experiment_objective"]["objective_id"] == objective
    assert result["experiment_objective"]["cost_permutation"] == expected_order
    expected_fields = actual_fields if objective == "production" else runner._OBJECTIVE_FIELDS
    assert result["experiment_objective"]["score_fields"] == [expected_fields[n] for n in expected_order]
    assert trace["actual_global_rescue_score_final"]["score_fields"] == result["experiment_objective"]["score_fields"]
    assert trace["actual_global_rescue_score_final"]["components"]["cps_excess_burden"] == 76000
    assert chunking._ordinary_grade({"ordinary"}) == (
        production_default_grade if objective == "production" else 2 if objective in {"U", "US"} else 3)


@pytest.mark.parametrize("objective", ("B", "U", "S", "US"))
def test_new_production_identity_rejects_second_objective_override(tmp_path, monkeypatch, objective):
    source = alignment(sections=False)
    source_path, media_path, cache_path = (tmp_path / name for name in ("source.json", "media.json", "cache.json"))
    runner.write_exclusive(source_path, source.to_dict())
    runner.write_exclusive(media_path, MediaBoundaryDTO("a" * 64, 3000, None).to_dict())
    identity = {"model_manifest_sha256": "b" * 64}
    runner.write_exclusive(cache_path, {"analyzer_identity": identity, "rows": []})
    import srt_processing.infrastructure.stanza_chunking as stanza_adapter
    monkeypatch.setattr(stanza_adapter, "StanzaConstituencyAnalyzer", lambda _: SimpleNamespace(identity=identity))
    monkeypatch.setattr(sys, "argv", ["synthetic-worker", str(source_path), str(media_path), str(cache_path), "no-model", "84", "{}", objective])
    with pytest.raises(ValueError, match="authorised frozen v3"):
        exec(runner._EVALUATION_WORKER, {"__name__": "__main__"})


def test_child_uses_selected_source_and_readonly_offline_environment(tmp_path, monkeypatch):
    selected = tmp_path / "frozen" / "src"
    selected.mkdir(parents=True)
    def run(argv, **kwargs):
        assert argv[:3] == [sys.executable, "-c", "synthetic worker"]
        assert kwargs["cwd"] == selected.parent
        assert kwargs["env"]["PYTHONPATH"] == str(selected)
        assert kwargs["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
        assert kwargs["env"]["HF_HUB_OFFLINE"] == kwargs["env"]["TRANSFORMERS_OFFLINE"] == "1"
        assert kwargs["check"] is True
        return SimpleNamespace(stdout='{"synthetic": true}\n')
    monkeypatch.setattr(runner.subprocess, "run", run)
    assert runner._child(selected, "synthetic worker", ()) == {"synthetic": True}


def test_exclusive_output_never_overwrites_existing_evidence(tmp_path):
    path = tmp_path / "frozen.json"
    runner.write_exclusive(path, {"retained": True})
    before = runner.fingerprint(path)
    with pytest.raises(FileExistsError):
        runner.write_exclusive(path, {"replacement": True})
    assert runner.fingerprint(path) == before


def test_code_snapshot_ignores_bytecode_but_not_source(tmp_path):
    (tmp_path / "code.py").write_text("pass\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__/code.pyc").write_bytes(b"cache")
    assert set(runner.code_snapshot(tmp_path)) == {"code.py"}


def test_sentence_deltas_keep_all_units_and_detect_shared_cue_merge():
    source, _ = labels_fixture()
    source["sentences"][0]["text"] = "Synthetic one."
    source["sentences"][1]["text"] = "Synthetic two."
    def cue(ids, sentences):
        return {"id": "synthetic", "word_ids": ids, "sentence_ids": sentences,
                "english_text": "Synthetic.", "start_ms": 100, "base_end_ms": 2000}
    separate = [cue(["w1", "w2", "w3", "w4"], ["s1"]), cue(["w5", "w6"], ["s2"])]
    merged = [cue([f"w{n}" for n in range(1, 7)], ["s1", "s2"])]
    results = {name: {"plan": {"chunks": deepcopy(separate)}} for name in ("old80", "old84", "new80", "new84")}
    results["new84"]["plan"]["chunks"] = merged
    results["new84_no_gap"] = {"plan": {"chunks": deepcopy(separate)}}
    report = runner.sentence_changes(source, results)
    assert report["fixed_source_unit_count"] == 2
    assert report["changed_sentences_by_pair"]["old80_to_new80"] == []
    assert report["changed_sentences_by_pair"]["new80_to_new84"] == ["s1", "s2"]
    assert report["changed_sentences_by_pair"]["new84_to_new84_no_gap"] == ["s1", "s2"]
    assert report["all_sentences"][1]["variants"]["new84"][0]["local_word_ids"] == ["w5", "w6"]
    assert report["all_sentences"][1]["variants"]["new84"][0]["whole_cue_start_ms"] == 100


def test_sentence_deltas_reject_missing_or_duplicate_coverage():
    source, _ = labels_fixture()
    for item in source["sentences"]:
        item["text"] = "Synthetic."
    bad = {"id": "synthetic", "word_ids": ["w1", "w3", "w4"], "sentence_ids": ["s1"],
           "english_text": "Synthetic.", "start_ms": 0, "base_end_ms": 1000}
    results = {name: {"plan": {"chunks": [bad]}} for name in ("old80", "old84", "new80", "new84")}
    with pytest.raises(ValueError, match="exactly once"):
        runner.sentence_changes(source, results)


def objective_fixture(tmp_path, monkeypatch):
    """Synthetic orchestration envelopes, not a mock claim of algorithm quality."""
    baseline, reference, production = (tmp_path / name for name in ("baseline", "reference", "production"))
    original, model = tmp_path / "original", tmp_path / "model"
    for folder in (baseline / "nb09_frozen", reference / "candidate_source/src", production / "src", original, model):
        folder.mkdir(parents=True)
    (production / "src/code.py").write_text("pass\n")
    (reference / "candidate_source/src/code.py").write_text("pass\n")
    monkeypatch.setattr(runner, "ROOT", production)
    monkeypatch.setattr(runner, "verify_baseline", lambda _: {"nb09_root": str(original)})
    source, labels = labels_fixture()
    for item in source["sentences"]:
        item["text"] = "Synthetic source."
    runner.write_exclusive(baseline / "nb09_frozen/source_alignment.json", source)
    runner.write_exclusive(baseline / "nb09_frozen/media_boundary.json", {"synthetic": True})
    runner.write_exclusive(baseline / "baseline_identity.json", {"synthetic": True})
    cache = tmp_path / "cache.json"
    runner.write_exclusive(cache, {"source_alignment": runner.fingerprint(baseline / "nb09_frozen/source_alignment.json")})
    labels["source_alignment_sha256"] = runner.fingerprint(baseline / "nb09_frozen/source_alignment.json")["sha256"]
    labels_path = tmp_path / "labels.json"
    runner.write_exclusive(labels_path, labels)
    runner.write_exclusive(reference / "frozen_human_labels.json", labels)
    runner.write_exclusive(reference / "experiment_evidence.json", {
        "candidate_source_snapshot_root": str(reference / "candidate_source/src"),
        "current_source_files": runner.code_snapshot(reference / "candidate_source/src"),
        "baseline_identity": runner.fingerprint(baseline / "baseline_identity.json"),
        "parse_cache": {"path": str(cache), **runner.fingerprint(cache)}})
    chunks = [{"id": f"k{n}", "word_ids": ids, "sentence_ids": [sid], "english_text": "Synthetic cue.",
               "start_ms": n * 1000, "base_end_ms": n * 1000 + 900}
              for n, ids, sid in ((1, ["w1", "w2", "w3", "w4"], "s1"), (2, ["w5", "w6"], "s2"))]
    control = {"chunks": chunks, "policy": {"synthetic": True}}
    runner.write_exclusive(reference / "new84.json", {"plan": control})
    output = tmp_path / "objective"
    return baseline, reference, cache, model, labels_path, output, control, production


def test_objective_plan_freezes_exact_two_factors_before_workers(tmp_path, monkeypatch):
    baseline, reference, cache, model, labels, output, _, _ = objective_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "_child", lambda *args: pytest.fail("preregistration cannot execute any worker"))
    result = runner.prepare_objective_experiment(baseline, reference, cache, model, labels, output)
    plan = json.loads((output / "experiment_plan.json").read_bytes())
    assert result["status"] == "preregistered-before-workers"
    assert plan["read_only_overrides"] and plan["no_manifest_publication"] and not plan["production_changed"]
    assert list(plan["variants"]["S"]["cost_permutation"]) == list(runner._OBJECTIVE_ORDER)
    assert plan["variants"]["US"]["score_fields"] == [runner._OBJECTIVE_FIELDS[n] for n in runner._OBJECTIVE_ORDER]
    assert all(item["cps_enabled"] and item["capacity"] == 84 for item in plan["variants"].values())
    assert not any((output / name).exists() for name in ("B", "U", "S", "US"))


@pytest.mark.parametrize("fault", (None, "B_drift", "source_write", "worker_drift"))
def test_objective_execution_guards_control_identity_sources_and_output_retention(tmp_path, monkeypatch, fault):
    baseline, reference, cache, model, labels, output, control, production = objective_fixture(tmp_path, monkeypatch)
    runner.prepare_objective_experiment(baseline, reference, cache, model, labels, output)
    plan = json.loads((output / "experiment_plan.json").read_bytes())
    calls = []
    def child(selected, code, args):
        name = args[-1]
        calls.append(name)
        assert selected == output / "candidate_source/src" and args[-2] == "{}" and args[-3] == 84
        result = {"plan": deepcopy(control), "experiment_objective": deepcopy(plan["variants"][name]),
                  "metrics": [{"id": f"k{n}", "characters": 14, "duration_ms": 900,
                               "shortfall_ms": 0, "cps_excess": 0, "empty_frames_to_next": 2, "issues": []} for n in (1, 2)]}
        if fault == "B_drift" and name == "B": result["plan"]["drift"] = True
        if fault == "source_write" and name == "US": (production / "src/code.py").write_text("changed\n")
        return result
    monkeypatch.setattr(runner, "_child", child)
    if fault == "worker_drift":
        (output / "experiment_worker.py").write_text("changed worker")
    if fault is not None:
        with pytest.raises((AssertionError, ValueError)):
            runner.execute_objective_experiment(output)
        assert not (output / "objective_evidence.json").exists()
        if fault == "B_drift":
            assert calls == ["B"] and (output / "B/result.json").is_file()
        if fault == "worker_drift": assert calls == []
        else: assert json.loads((output / "failure.json").read_bytes())["status"] == "failed"
    else:
        result = runner.execute_objective_experiment(output)
        assert calls == ["B", "U", "S", "US"]
        evidence = json.loads((output / "objective_evidence.json").read_bytes())
        assert result["summary"]["B"]["cue_count"] == 2
        assert evidence["control_B_matches_v4_complete_plan"] and evidence["protected_sources_and_production_unchanged"]
        assert evidence["human_quality"] == "not_assessed"
        with pytest.raises(ValueError, match="unused variant"):
            runner.execute_objective_experiment(output)
