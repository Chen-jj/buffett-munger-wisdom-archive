import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.srt_processing import candidate_v3_runner as v3
from tests.srt_processing import candidate_runner as v2


def test_v3_cli_is_opt_in_and_does_not_create_output(tmp_path,capsys):
    target=tmp_path/'never'
    assert v3.main(['--experiment-root',str(target)])==2
    assert json.loads(capsys.readouterr().out)['status']=='opt_in_required'
    assert not target.exists()


def test_v3_prepare_receipt_preserves_originals_and_refuses_reprepare(tmp_path,capsys):
    from tests.srt_processing.test_candidate_runner import upstream_fixture
    root,source=upstream_fixture(tmp_path)
    experiment=tmp_path/'experiment';experiment.mkdir()
    v2.write_json(experiment/'protected_before.v1.json',{'source':{'root':str(source),'files':v2.snapshot(source)}})
    assert v3.main(['--prepare','--source-root',str(root),'--experiment-root',str(experiment)])==0
    assert json.loads(capsys.readouterr().out)['status']=='passed'
    assert (experiment/'workflow.v1.json.run.protected_after.json').is_file()
    assert (experiment/'preparation.v1.json').is_file()
    with pytest.raises(FileExistsError):v3.main(['--prepare','--source-root',str(root),'--experiment-root',str(experiment)])
    assert v2.verify_protected(experiment)['source']['unchanged']


def test_sentence_local_fragment_does_not_imply_shared_cue_is_duplicated():
    words=[SimpleNamespace(text='Earlier.',start_ms=0,end_ms=500),SimpleNamespace(text='I',start_ms=520,end_ms=600),SimpleNamespace(text='mean,',start_ms=620,end_ms=900)]
    cue={'id':'c1','start_ms':0,'end_ms':950,'english_text':'Earlier. I mean,','chinese_text':'之前。我是说，','fragments':[
        {'sentence_id':'s18','first_word_id':'w1','last_word_id':'w1','chinese_start_offset':0,'chinese_end_offset':3,'speaker_label':None},
        {'sentence_id':'s19','first_word_id':'w2','last_word_id':'w3','chinese_start_offset':0,'chinese_end_offset':4,'speaker_label':None}]}
    item=v3.sentence_local(cue,'s19',SimpleNamespace(words=words),{'s18':'之前。','s19':'我是说，'})
    assert len(item['sentence_local_fragments'])==1
    assert item['sentence_local_fragments'][0]['chinese_text']=='我是说，'
    assert item['sentence_local_fragments'][0]['english_text']=='I mean,'
    assert item['full_shared_cue']['english_text']=='Earlier. I mean,'
    assert item['associated_sentence_ids']==['s18','s19']
    assert item['sentence_local_fragments'][0]['local_source_start_ms']==520


def audit_fixture(text,duration=9744):
    alignment=SimpleNamespace(words=[SimpleNamespace(text='Statement.',start_ms=0,end_ms=duration)],
        sentences=[SimpleNamespace(id='s1',first_word_id='w1',last_word_id='w1',speaker_label=None)],
        sections=[SimpleNamespace(id='sec1',first_sentence_id='s1',last_sentence_id='s1')],audio_duration_ms=duration+1000)
    translation=SimpleNamespace(sentence_translations=[SimpleNamespace(sentence_id='s1',translated_text=text)])
    cue={'id':'c1','section_id':'sec1','start_ms':0,'base_end_ms':duration,'end_ms':duration,'english_text':'Statement.','chinese_text':text,
         'fragments':[{'sentence_id':'s1','first_word_id':'w1','last_word_id':'w1','chinese_start_offset':0,'chinese_end_offset':len(text),'speaker_label':None}]}
    return alignment,translation,[cue]


@pytest.mark.parametrize('duration,over7,high_cps',[(9744,True,False),(1200,False,True)])
def test_v3_soft_targets_do_not_become_hard_rejections(duration,over7,high_cps):
    alignment,translation,cues=audit_fixture('这是一段完整而且非常长的中文句子内容。',duration)
    original=json.dumps(cues,ensure_ascii=False)
    result=v3.inspect_v3_cues(cues,alignment,translation)[0]
    assert result['hard_compatible_v3']
    assert result['soft_warnings']['chinese_units_over16']
    assert result['soft_warnings']['display_duration_over7000ms']==over7
    assert result['soft_warnings']['chinese_cps_over9']==high_cps
    assert json.dumps(cues,ensure_ascii=False)==original


def test_v3_soft_targets_have_no_hidden_10_second_cap():
    alignment,translation,cues=audit_fixture('完整句。',12001)
    result=v3.inspect_v3_cues(cues,alignment,translation)[0]
    assert result['hard_compatible_v3']
    assert result['soft_warnings']['display_duration_over7000ms']


def test_v3_rejects_nonpause_cut_without_repair():
    text='完整的中文句子。'
    alignment=SimpleNamespace(words=[SimpleNamespace(text='One',start_ms=0,end_ms=1000),SimpleNamespace(text='two.',start_ms=1100,end_ms=2100)],
        sentences=[SimpleNamespace(id='s1',first_word_id='w1',last_word_id='w2',speaker_label=None)],sections=[],audio_duration_ms=3000)
    translation=SimpleNamespace(sentence_translations=[SimpleNamespace(sentence_id='s1',translated_text=text)])
    cues=[{'id':'c1','start_ms':0,'base_end_ms':1000,'end_ms':1000,'english_text':'One','chinese_text':text[:3],
           'fragments':[{'sentence_id':'s1','first_word_id':'w1','last_word_id':'w1','chinese_start_offset':0,'chinese_end_offset':3,'speaker_label':None}]},
          {'id':'c2','start_ms':1100,'base_end_ms':2100,'end_ms':2100,'english_text':'two.','chinese_text':text[3:],
           'fragments':[{'sentence_id':'s1','first_word_id':'w2','last_word_id':'w2','chinese_start_offset':3,'chinese_end_offset':len(text),'speaker_label':None}]}]
    result=v3.inspect_v3_cues(cues,alignment,translation)
    assert result[0]['pause_boundary_violations']==[{'sentence_id':'s1','offset':3}]
    assert 'chinese_nonpause_boundary' in result[0]['hard_issues']


def test_v3_runner_independent_projection_and_warning_sets_after_real_workflow(tmp_path):
    from tests.srt_processing.acceptance_fakes import LocalCase
    from tests.srt_processing.sample_runner import run_local_sample
    case=LocalCase(tmp_path)
    result=run_local_sample(asset_id=case.asset.value,output_root=case.root,probe=case.probe,clock=case.clock)
    assert result['status']=='passed'
    assert result['first_status']=='succeeded' and result['second_status']=='reused'
    assert result['reuse_write_count']==0
    audit=v3.verify_v3_projection(case.workspace)
    assert audit['all_hard_qa_passed'] and audit['three_srt_independent_readback']
    assert audit['sentences']==3 and audit['source_words_exactly_once']==7
    assert set(audit['report_soft_warning_cue_sets_verified'])=={'reading.chinese_length','timing.target_duration','reading.chinese_cps'}


def test_preflight_only_emits_capacity_counts_not_selected_cuts(tmp_path):
    from tests.srt_processing.acceptance_fakes import LocalCase
    case=LocalCase(tmp_path)
    target=tmp_path/'preflight.json'
    result=v3.preflight(case.workspace,target)
    assert result['sentences']==3
    report=v2.read_json(target)
    assert all('minimum_ordered_source_word_line_count' in row for row in report['sentences'])
    assert not any(path.exists() for path in case.outputs.values())
    assert all('selected_cues' not in row and 'english_line_break_offsets' not in row for row in report['sentences'])
