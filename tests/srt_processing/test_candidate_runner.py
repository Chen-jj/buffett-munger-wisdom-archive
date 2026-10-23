import json
from pathlib import Path

import pytest

from tests.srt_processing import candidate_runner as runner


def upstream_fixture(tmp_path):
    source_root=tmp_path/'source'
    source=runner.build_asset_workspace(runner.ASSET,source_root)
    source.mkdir(parents=True)
    for name in ('source_alignment.json','translation_result.json','translation_manifest.json'):
        (source/name).write_text('{}\n')
    for name in ('video.mp4','audio.wav'):
        (source/name).write_bytes(b'fixture media, no external tool')
    records={key:{'path':str(source/name),'sha256':'a'*64} for key,name in [('audio','audio.wav'),('source_alignment','source_alignment.json')]}
    (source/'transcription_manifest.json').write_text(json.dumps({'records':records}))
    (source/'subtitle_plan.json').write_text('old output is not an upstream input')
    return source_root,source


def test_cli_no_opt_in_has_no_filesystem_effect(tmp_path,capsys):
    target=tmp_path/'never-created'
    assert runner.main(['--experiment-root',str(target)])==2
    assert json.loads(capsys.readouterr().out)['status']=='opt_in_required'
    assert not target.exists()


def test_prepare_requires_existing_upstream_before_mkdir(tmp_path):
    with pytest.raises(ValueError,match='missing existing upstream'):
        runner.prepare_candidate_workspace(tmp_path/'empty',tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_prepare_rebases_only_derived_manifest_and_links_media(tmp_path):
    root,source=upstream_fixture(tmp_path)
    before=runner.snapshot(source)
    out=tmp_path/'out'
    result=runner.prepare_candidate_workspace(root,out)
    target=runner.build_asset_workspace(runner.ASSET,out)
    assert runner.snapshot(source)==before
    assert result['source_unchanged']
    assert not (target/'subtitle_plan.json').exists()
    for name in ('audio.wav','video.mp4'):
        assert (target/name).is_symlink()
        assert (target/name).read_bytes()==(source/name).read_bytes()
    for row in runner.read_json(target/'transcription_manifest.json')['records'].values():
        assert Path(row['path']).parent==target
        assert row['sha256']=='a'*64
    assert (target/'source_alignment.json').read_bytes()==(source/'source_alignment.json').read_bytes()


def test_prepare_does_not_overwrite_existing_candidate(tmp_path):
    root,_=upstream_fixture(tmp_path);out=tmp_path/'out'
    runner.prepare_candidate_workspace(root,out)
    before=runner.snapshot(out)
    with pytest.raises(FileExistsError,match='refusing to overwrite'):
        runner.prepare_candidate_workspace(root,out)
    assert runner.snapshot(out)==before


def test_exclusive_json_write_preserves_original(tmp_path):
    path=tmp_path/'evidence.json';runner.write_json(path,{'a':1})
    before=runner.evidence(path)
    with pytest.raises(FileExistsError):runner.write_json(path,{'a':2})
    assert runner.evidence(path)==before


def test_protected_tree_detects_bytes_metadata_and_new_file(tmp_path):
    protected=tmp_path/'protected';protected.mkdir();(protected/'a').write_bytes(b'a')
    experiment=tmp_path/'experiment';experiment.mkdir()
    runner.write_json(experiment/'protected_before.v1.json',{'fixture':{'root':str(protected),'files':runner.snapshot(protected)}})
    assert runner.verify_protected(experiment)['fixture']['unchanged']
    (protected/'new').write_bytes(b'new')
    with pytest.raises(ValueError,match='protected original files changed'):runner.verify_protected(experiment)


def test_candidate_full_workflow_projection_and_fixed_reference_comparison(tmp_path):
    from dataclasses import replace
    from tests.srt_processing.acceptance_fakes import LocalCase, default_data
    from tests.srt_processing.sample_runner import run_local_sample
    alignment, translation, media = default_data()
    # Keep this generic integration fixture within both v2 hard and v3 soft
    # budgets; do not change the historical v2 verifier's fixed policy.
    first, *rest = translation.sentence_translations
    translation = replace(translation, sentence_translations=(replace(first, translated_text="我们保留译文，"), *rest))
    case=LocalCase(tmp_path, data=(alignment, translation, media))
    assert case.handler().handle(case.command).status=='succeeded'
    out=tmp_path/'candidate'
    runner.prepare_candidate_workspace(Path(case.root),out,case.asset)
    result=run_local_sample(asset_id=case.asset.value,output_root=str(out),probe=case.probe,clock=case.clock)
    assert result['status']=='passed' and result['first_status']=='succeeded' and result['second_status']=='reused'
    target=runner.build_asset_workspace(case.asset,out)
    assert runner.verify_candidate_projection(target)['three_srt_independent_readback']
    evidence=runner.compare_three(case.workspace,target,case.outputs['subtitle_plan'],tmp_path/'comparison')
    assert evidence['sentences']==3 and evidence['candidate_same_cuts_as_agent153']==3
    notes=tmp_path/'manual.jsonl'
    notes.write_text(''.join(json.dumps({'sentence_id':f's{i}','candidate_vs_old':'平','candidate_vs_agent':'平','reason':'hand-written test fixture','residual':'not a semantic approval'})+'\n' for i in range(1,4)))
    reviewed=runner.join_manual_review(tmp_path/'comparison',notes,tmp_path/'review')
    assert reviewed['reviewed_sentences']==3
    assert (tmp_path/'review/all_sentences.md').read_text().count('## s')==3
    with pytest.raises(FileExistsError):runner.join_manual_review(tmp_path/'comparison',notes,tmp_path/'review')


def test_fixed_reference_audit_checks_real_packing_not_84_total():
    from types import SimpleNamespace
    words=[SimpleNamespace(start_ms=i*1000,end_ms=i*1000+900) for i in range(3)]
    sentence=SimpleNamespace(id='s1',first_word_id='w1',last_word_id='w3',speaker_label=None)
    alignment=SimpleNamespace(words=words,sentences=[sentence])
    translation=SimpleNamespace(sentence_translations=[SimpleNamespace(sentence_id='s1',translated_text='测试。')])
    cue={'id':'a1','start_ms':0,'base_end_ms':2900,'end_ms':2900,
         'english_text':'a'*28+' '+'b'*28+' '+'c'*28,'chinese_text':'测试。',
         'fragments':[{'sentence_id':'s1','first_word_id':'w1','last_word_id':'w3','chinese_start_offset':0,'chinese_end_offset':3,'speaker_label':None}]}
    rows=runner.inspect_cues([cue],alignment,translation)
    assert rows[0]['english_nonspace_characters']==84
    assert rows[0]['hard_issues']==['english_2x42_not_packable']


def test_fixed_reference_audit_uses_new_word_counts_without_changing_cut_or_time():
    from types import SimpleNamespace
    alignment=SimpleNamespace(words=[SimpleNamespace(start_ms=10,end_ms=1500)],sentences=[SimpleNamespace(id='s1',first_word_id='w1',last_word_id='w1',speaker_label=None)])
    text='Berkshire Hathaway。'
    translation=SimpleNamespace(sentence_translations=[SimpleNamespace(sentence_id='s1',translated_text=text)])
    cue={'id':'a1','start_ms':10,'base_end_ms':1500,'end_ms':1500,'english_text':'Berkshire Hathaway.','chinese_text':text,
         'fragments':[{'sentence_id':'s1','first_word_id':'w1','last_word_id':'w1','chinese_start_offset':0,'chinese_end_offset':len(text),'speaker_label':None}]}
    before=json.dumps(cue,sort_keys=True)
    result=runner.inspect_cues([cue],alignment,translation)
    assert result[0]['chinese_word_units']==3
    assert result[0]['hard_compatible_candidate_profile']
    assert json.dumps(cue,sort_keys=True)==before


def test_old_reference_hard_latin_cut_is_reported_not_repaired():
    from types import SimpleNamespace
    text='Berkshire。'
    words=[SimpleNamespace(start_ms=0,end_ms=1500),SimpleNamespace(start_ms=1600,end_ms=3000)]
    alignment=SimpleNamespace(words=words,sentences=[SimpleNamespace(id='s1',first_word_id='w1',last_word_id='w2',speaker_label=None)])
    translation=SimpleNamespace(sentence_translations=[SimpleNamespace(sentence_id='s1',translated_text=text)])
    cues=[{'id':'a1','start_ms':0,'base_end_ms':1500,'end_ms':1500,'english_text':'One','chinese_text':'Berk',
           'fragments':[{'sentence_id':'s1','first_word_id':'w1','last_word_id':'w1','chinese_start_offset':0,'chinese_end_offset':4,'speaker_label':None}]},
          {'id':'a2','start_ms':1600,'base_end_ms':3000,'end_ms':3000,'english_text':'Two.','chinese_text':'shire。',
           'fragments':[{'sentence_id':'s1','first_word_id':'w2','last_word_id':'w2','chinese_start_offset':4,'chinese_end_offset':len(text),'speaker_label':None}]}]
    before=json.dumps(cues,sort_keys=True)
    rows=runner.inspect_cues(cues,alignment,translation)
    assert rows[0]['hard_issues']==['hard_chinese_token_boundary']
    assert json.dumps(cues,sort_keys=True)==before
