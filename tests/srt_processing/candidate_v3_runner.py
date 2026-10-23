"""Opt-in isolated v3 acceptance: no upstream generation and no cue selection.

Only run after SP13/14 runtime freeze. Old v2 runner and saved artifacts stay intact.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from archive_core.application import build_asset_workspace
from archive_core.interfaces import SourceAlignmentDTO, TranslationResultDTO, SubtitlePlanDTO, normalize_chinese_text, reconstruct_sentence_text
from tests.srt_processing.candidate_runner import (
    ASSET, DEFAULT_SOURCE, DEFAULT_REFERENCE, read_json, write_json, evidence,
    prepare_candidate_workspace, inspect_cues as inspect_v2_cues, verify_protected,
)

DEFAULT_EXPERIMENT=Path('output/cue-evaluation/20261023-candidate-v3')
DEFAULT_V2_PLAN=Path('output/cue-evaluation/20261022-candidate-v2/workspaces/cnbc_2000_morning/subtitle_plan.json')


def inspect_v3_cues(cues, alignment, translation, usable_duration_ms=None, gap_threshold_ms=67):
    """Validate fixed cuts; soft targets never trigger splitting or hard rejection."""
    from srt_processing.domain.boundaries import chinese_pause_boundaries
    from srt_processing.domain.rules import chinese_half_units, adjust_cue_timing
    # Reuse source-word/Chinese-cursor/English actual packing checks, not v2 policy.
    records=inspect_v2_cues(cues,alignment,translation)
    chinese={r.sentence_id:normalize_chinese_text(r.translated_text) for r in translation.sentence_translations}
    sentences={s.id:s for s in alignment.sentences}
    sections={}
    for section in alignment.sections:
        for i in range(int(section.first_sentence_id[1:]),int(section.last_sentence_id[1:])+1):sections[f's{i}']=section.id
    previous_end=0
    for cue,row in zip(cues,records,strict=True):
        hard=[issue for issue in row['hard_issues'] if issue not in ('chinese_word_count_gt16','duration_gt7000','candidate_count_merge_qualification','hard_chinese_token_boundary')]
        pause_violations=[]
        for f in cue['fragments']:
            if f['chinese_end_offset'] not in chinese_pause_boundaries(chinese[f['sentence_id']]):
                pause_violations.append({'sentence_id':f['sentence_id'],'offset':f['chinese_end_offset']})
        if pause_violations:hard.append('chinese_nonpause_boundary')
        if len({sections.get(f['sentence_id']) for f in cue['fragments']})>1:hard.append('cross_section')
        if len({f['speaker_label'] for f in cue['fragments'] if f['speaker_label'] is not None})>1:hard.append('cross_known_speakers')
        if len(cue['fragments'])>1:
            first_part=cue['fragments'][0]
            first_index=int(first_part['first_word_id'][1:])-1
            first_end=int(first_part['last_word_id'][1:])
            original_duration=alignment.words[first_end-1].end_ms-alignment.words[first_index].start_ms
            first_units=chinese_half_units(chinese[first_part['sentence_id']][first_part['chinese_start_offset']:first_part['chinese_end_offset']])
            single=adjust_cue_timing(start_ms=alignment.words[first_index].start_ms,base_end_ms=alignment.words[first_end-1].end_ms,
                chinese_units=first_units,english_count=0,usable_duration_ms=alignment.audio_duration_ms if usable_duration_ms is None else usable_duration_ms,
                gap_threshold_ms=gap_threshold_ms,next_start_ms=alignment.words[first_end].start_ms if first_end<len(alignment.words) else None)
            if original_duration>=834 or not single.too_short:hard.append('cross_sentence_not_unrescuable_short_tail')
            for f in cue['fragments'][1:]:
                sentence=sentences[f['sentence_id']]
                if not (f['first_word_id']==sentence.first_word_id and f['last_word_id']==sentence.last_word_id
                        and f['chinese_start_offset']==0 and f['chinese_end_offset']==len(chinese[f['sentence_id']])):
                    hard.append('partial_next_sentence_borrowed')
            for left,right in zip(cue['fragments'],cue['fragments'][1:]):
                ls,rs=sentences[left['sentence_id']],sentences[right['sentence_id']]
                gap=alignment.words[int(rs.first_word_id[1:])-1].start_ms-alignment.words[int(ls.last_word_id[1:])-1].end_ms
                if gap>=500:hard.append('cross_sentence_gap_not_below500ms')
        last=int(cue['fragments'][-1]['last_word_id'][1:]);base=alignment.words[last-1].end_ms
        if cue['base_end_ms']!=base or not base<=cue['end_ms']<=base+500:hard.append('source_end_or_extension_budget')
        limit=alignment.audio_duration_ms if usable_duration_ms is None else usable_duration_ms
        if cue['end_ms']>limit or cue['start_ms']<previous_end or cue['end_ms']<=cue['start_ms']:hard.append('timeline_or_media_boundary')
        if last<len(alignment.words) and cue['end_ms']>alignment.words[last].start_ms:hard.append('extension_crosses_next_speech')
        previous_end=cue['end_ms']
        row['hard_issues']=sorted(set(hard))
        row.pop('hard_compatible_candidate_profile',None)
        row['hard_compatible_v3']=not hard
        row['pause_boundary_violations']=pause_violations
        row['soft_warnings']={
            'chinese_units_over16':chinese_half_units(cue['chinese_text'])>32,
            'display_duration_over7000ms':row['duration_ms']>7000,
            'chinese_cps_over9':row['chinese_cps_gt9'],
            'english_cps_over17':row['english_cps_gt17'],
            'duration_under834ms':row['duration_ms']<834,
        }
    return records


def verify_v3_projection(workspace):
    import pysubs2
    from srt_processing.domain.rules import wrap_english_text
    plan=SubtitlePlanDTO.from_dict(read_json(workspace/'subtitle_plan.json'))
    alignment=SourceAlignmentDTO.from_dict(read_json(workspace/'source_alignment.json'))
    translation=TranslationResultDTO.from_dict(read_json(workspace/'translation_result.json'))
    plan.validate_against_inputs(alignment,translation)
    rows=inspect_v3_cues([c.to_dict() for c in plan.cues],alignment,translation,plan.media.usable_duration_ms,plan.media.gap_threshold_ms)
    assert all(r['hard_compatible_v3'] for r in rows), 'candidate fails v3 hard QA (soft warnings are permitted)'
    for language in ('english','chinese','bilingual'):
        data=(workspace/f'{language}.srt').read_bytes()
        assert data.endswith(b'\n') and b'\r' not in data and not data.startswith(b'\xef\xbb\xbf')
        subs=pysubs2.SSAFile.from_string(data.decode('utf-8'),format_='srt')
        assert len(subs)==len(plan.cues)
        for event,cue in zip(subs,plan.cues,strict=True):
            wrapped=wrap_english_text(cue.english_text)
            expected=wrapped if language=='english' else cue.chinese_text if language=='chinese' else cue.chinese_text+'\n'+wrapped
            assert (event.start,event.end,event.plaintext)==(cue.start_ms,cue.end_ms,expected)
            assert len(event.plaintext.split('\n')) <= {'english':2,'chinese':1,'bilingual':3}[language]
    report=read_json(workspace/'srt_processing_report.json')
    observed={code:{cid for finding in report['findings'] if finding['code']==code for cid in finding['cue_ids']}
              for code in ('reading.chinese_length','timing.target_duration','reading.chinese_cps')}
    expected={
        'reading.chinese_length':{r['cue_id'] for r in rows if r['soft_warnings']['chinese_units_over16']},
        'timing.target_duration':{r['cue_id'] for r in rows if r['soft_warnings']['display_duration_over7000ms']},
        'reading.chinese_cps':{r['cue_id'] for r in rows if r['soft_warnings']['chinese_cps_over9']},
    }
    assert observed==expected, 'report soft-warning cue sets do not match independent fixed-cut audit'
    for finding in report['findings']:
        if finding['code'] in expected:assert finding['severity']=='warning'
    return {'source_words_exactly_once':len(alignment.words),'sentences':len(alignment.sentences),'sections':len(alignment.sections),
            'normalized_chinese_codepoints_exactly_once':sum(len(normalize_chinese_text(r.translated_text)) for r in translation.sentence_translations),
            'three_srt_independent_readback':True,'all_hard_qa_passed':True,'report_soft_warning_cue_sets_verified':{key:sorted(value) for key,value in expected.items()},'cue_metrics':rows}


def sentence_local(cue,sid,alignment,chinese):
    """Do not present a full shared cue as if all its content belongs to one sentence."""
    local=[]
    for f in cue['fragments']:
        if f['sentence_id']!=sid:continue
        first=int(f['first_word_id'][1:])-1;end=int(f['last_word_id'][1:])
        local.append(dict(f,english_text=reconstruct_sentence_text(alignment.words[first:end]),
                          chinese_text=chinese[sid][f['chinese_start_offset']:f['chinese_end_offset']],
                          local_source_start_ms=alignment.words[first].start_ms,local_source_end_ms=alignment.words[end-1].end_ms))
    return {'cue_id':cue['id'],'sentence_local_fragments':local,
            'associated_sentence_ids':list(dict.fromkeys(f['sentence_id'] for f in cue['fragments'])),
            'full_shared_cue':cue,
            'association_note':'One plan cue; repeated sentence association is not duplicate artifact coverage.'}


def compare_four(source,candidate,v2_path,reference_path,out):
    from srt_processing.domain.rules import PROFILE
    alignment=SourceAlignmentDTO.from_dict(read_json(source/'source_alignment.json'))
    translation=TranslationResultDTO.from_dict(read_json(source/'translation_result.json'))
    chinese={r.sentence_id:normalize_chinese_text(r.translated_text) for r in translation.sentence_translations}
    plans={'v1_242':read_json(source/'subtitle_plan.json'),'v2_224':read_json(v2_path),
           'agent153':read_json(reference_path),'v3':read_json(candidate/'subtitle_plan.json')}
    audits={name:inspect_v3_cues(p['cues'],alignment,translation,p['media']['usable_duration_ms'],p['media']['gap_threshold_ms']) for name,p in plans.items()}
    lookup={name:{r['cue_id']:r for r in rows} for name,rows in audits.items()}
    parent={s.id:s.id for s in alignment.sentences}
    def root(sid):
        while parent[sid]!=sid:sid=parent[sid]
        return sid
    for p in plans.values():
        for cue in p['cues']:
            sids=[f['sentence_id'] for f in cue['fragments']]
            for sid in sids[1:]:parent[root(sid)]=root(sids[0])
    groups={}
    for sid in parent:groups.setdefault(root(sid),[]).append(sid)
    rows=[]
    for s in alignment.sentences:
        row={'sentence_id':s.id,'source_english':s.text,'source_chinese':chinese[s.id],'comparison_group_sentence_ids':groups[root(s.id)]}
        for name,p in plans.items():
            row[name]=[]
            for cue in p['cues']:
                if any(f['sentence_id']==s.id for f in cue['fragments']):
                    item=sentence_local(cue,s.id,alignment,chinese)
                    item['v3_fixed_cut_audit']=lookup[name][cue['id']]
                    row[name].append(item)
            linked=[c for c in p['cues'] if any(f['sentence_id'] in row['comparison_group_sentence_ids'] for f in c['fragments'])]
            row[name+'_complete_group_hard_compatible_v3']=all(lookup[name][c['id']]['hard_compatible_v3'] for c in linked)
        rows.append(row)
    out.mkdir()
    with (out/'four_way_sentences.jsonl').open('x',encoding='utf-8') as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n')
    summary={}
    for name,items in audits.items():
        summary[name]={'cue_count':len(items),'hard_incompatible_v3':sum(not r['hard_compatible_v3'] for r in items),
                       'pause_boundary_violation_cues':sum(bool(r['pause_boundary_violations']) for r in items),
                       'cross_sentence_cues':sum(len(c['fragments'])>1 for c in plans[name]['cues']),
                       'warnings':{key:sum(r['soft_warnings'][key] for r in items) for key in items[0]['soft_warnings']}}
    write_json(out/'four_way_metrics.json',{'method':'Frozen cuts and original times, re-audited under explicit v3 hard vs soft policy; no planning',
                                          'current_profile':PROFILE.to_dict(),'summary':summary,'cue_metrics':audits})
    return {'sentences':len(rows),'summary':summary}


def join_review(comparison,notes_path,checklist_path,out):
    rows=[json.loads(l) for l in (comparison/'four_way_sentences.jsonl').read_text().splitlines()]
    notes=[json.loads(l) for l in notes_path.read_text().splitlines() if l.strip()]
    by_sid={r['sentence_id']:r for r in notes};checklist=read_json(checklist_path)
    expected={r['sentence_id']:r for r in checklist['rows']}
    assert len(by_sid)==len(notes)==len(rows) and set(by_sid)=={r['sentence_id'] for r in rows}
    out.mkdir();preferences=[]
    with (out/'all_97_sentences.md').open('x',encoding='utf-8') as md,(out/'all_97_sentences.jsonl').open('x',encoding='utf-8') as js:
        md.write('# 全97句四方对照\n\n先列sentence-local片段；跨句完整cue仅作关联说明，不是每句都包含全文，更不是资产重复。所有评价是agent文本审读，非音画/出版签字。16/7秒/9CPS为warning，不作硬不合法。\n')
        for row in rows:
            note=by_sid[row['sentence_id']];row['manual_review']=note
            if row['sentence_id'] in expected:
                assert note['preference_status'] in ('满足','允许变体','部分','未满足')
                preferences.append({'sentence_id':row['sentence_id'],'preference':expected[row['sentence_id']],
                                    'status':note['preference_status'],'reason':note['preference_reason']})
            md.write('\n## '+row['sentence_id']+'\n\n源英文：'+row['source_english']+'\n\n源中文：'+row['source_chinese']+'\n\n')
            md.write('**独立审读**：'+note['reason']+'\n\n**残余/代价**：'+note['residual']+'\n\n')
            if row['sentence_id'] in expected:md.write('**用户偏好：'+note['preference_status']+'** — '+note['preference_reason']+'\n\n')
            md.write('完整关联句组：'+', '.join(row['comparison_group_sentence_ids'])+'。\n')
            for name in ('v1_242','v2_224','agent153','v3'):
                md.write('\n### '+name+' · 完整组v3硬兼容='+str(row[name+'_complete_group_hard_compatible_v3'])+'\n')
                for item in row[name]:
                    cue=item['full_shared_cue'];audit=item['v3_fixed_cut_audit']
                    md.write('\n- **'+item['cue_id']+' 本句片段**（关联句 '+', '.join(item['associated_sentence_ids'])+'）\n')
                    for f in item['sentence_local_fragments']:
                        md.write('  - '+f['first_word_id']+'–'+f['last_word_id']+'；中文offset '+str(f['chinese_start_offset'])+'–'+str(f['chinese_end_offset'])+'；本片段源时间 '+str(f['local_source_start_ms'])+'–'+str(f['local_source_end_ms'])+'ms\n')
                        md.write('  - 本句中文：'+f['chinese_text']+'\n  - 本句英文：'+f['english_text']+'\n')
                    md.write('  - 整cue显示时间 '+str(cue['start_ms'])+'–'+str(cue['end_ms'])+'ms；硬问题 '+str(audit['hard_issues'])+'；warning '+str(audit['soft_warnings'])+'\n')
                    md.write('  - 整cue英文行：'+(' ↵ '.join(audit['english_lines']) or '不可排：'+str(audit['english_layout_error']))+'\n')
                    if len(item['associated_sentence_ids'])>1:
                        md.write('  - **完整关联cue（仅一个计划工件）**：'+cue['chinese_text']+' / '+cue['english_text']+'\n')
            js.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n')
    write_json(out/'user_preference_acceptance.json',{'reviewed_preferences':len(preferences),'rows':preferences})
    with (out/'user_preference_acceptance.md').open('x',encoding='utf-8') as f:
        f.write('# 用户偏好逐项验收\n\n|句|状态|客观理由/允许变体|\n|---|---|---|\n')
        for r in preferences:f.write('|'+r['sentence_id']+'|'+r['status']+'|'+r['reason'].replace('|','／')+'|\n')
    return {'reviewed_sentences':len(rows),'reviewed_preferences':len(preferences),'notes_evidence':evidence(notes_path)}



def preflight(source,out):
    """Necessary capacity evidence only; count minimum English lines, emit no cuts."""
    from srt_processing.domain.boundaries import chinese_pause_boundaries
    from srt_processing.domain.rules import wrap_english_text, english_characters
    alignment=SourceAlignmentDTO.from_dict(read_json(source/'source_alignment.json'))
    translation=TranslationResultDTO.from_dict(read_json(source/'translation_result.json'))
    chinese={r.sentence_id:normalize_chinese_text(r.translated_text) for r in translation.sentence_translations}
    rows=[]
    for sentence in alignment.sentences:
        allowed=chinese_pause_boundaries(chinese[sentence.id])
        words=alignment.words[int(sentence.first_word_id[1:])-1:int(sentence.last_word_id[1:])]
        counts=[english_characters(w.text) for w in words]
        oversized=[w.id for w,c in zip(words,counts,strict=True) if c>42]
        minimum_lines=1;used=0
        for count in counts:
            if used+count>42:minimum_lines+=1;used=count
            else:used+=count
        maximum_units=len(allowed)-1
        try:wrap_english_text(sentence.text);whole_packable=True
        except ValueError:whole_packable=False
        issues=[]
        if oversized:issues.append('indivisible_source_word_over42')
        if maximum_units==1 and not whole_packable:issues.append('one_chinese_unit_but_english_not_2x42')
        if minimum_lines>2*maximum_units:issues.append('minimum_english_line_count_exceeds_chinese_units_times2')
        rows.append({'sentence_id':sentence.id,'chinese_allowed_pause_offsets':list(allowed),'maximum_chinese_units':maximum_units,
                     'source_word_count':len(words),'oversized_source_words':oversized,'english_nonspace_count':sum(counts),
                     'whole_english_packable':whole_packable,'minimum_ordered_source_word_line_count':minimum_lines,
                     'necessary_infeasibility_evidence':issues})
    result={'method':'Necessary-condition screening only, no English cue ranges/Chinese cuts selected, no DP, no fallback. Absence of findings is not full bilingual feasibility proof.',
            'runtime_may_not_be_frozen':True,'sentences':rows,'infeasibility_evidence':[r for r in rows if r['necessary_infeasibility_evidence']]}
    write_json(out,result)
    return {'sentences':len(rows),'necessary_infeasibility_count':len(result['infeasibility_evidence'])}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ('prepare','run','compare','preflight'):parser.add_argument('--'+flag,action='store_true')
    parser.add_argument('--experiment-root',type=Path,default=DEFAULT_EXPERIMENT)
    parser.add_argument('--source-root',type=Path,default=DEFAULT_SOURCE)
    parser.add_argument('--v2-plan',type=Path,default=DEFAULT_V2_PLAN);parser.add_argument('--reference-plan',type=Path,default=DEFAULT_REFERENCE)
    parser.add_argument('--preflight-name',default='preflight_count.v1.json')
    parser.add_argument('--result-name',default='workflow.v1.json');parser.add_argument('--comparison-name',default='comparison_v1')
    parser.add_argument('--review-notes',type=Path);parser.add_argument('--review-name',default='review_v1')
    parser.add_argument('--ffprobe-executable',default='ffprobe')
    args=parser.parse_args(argv)
    if not any((args.prepare,args.run,args.compare,args.preflight,args.review_notes)):
        print(json.dumps({'status':'opt_in_required'}));return 2
    args.experiment_root.mkdir(parents=True,exist_ok=True)
    output_root=args.experiment_root.resolve()/'workspaces';workspace=build_asset_workspace(ASSET,output_root)
    result={}
    if args.preflight:
        result['preflight']=preflight(build_asset_workspace(ASSET,args.source_root.resolve()),args.experiment_root/args.preflight_name)
    if args.prepare:write_json(args.experiment_root/'preparation.v1.json',prepare_candidate_workspace(args.source_root,output_root))
    if args.run:
        from tests.srt_processing.sample_runner import run_local_sample
        result=run_local_sample(output_root=str(output_root),ffprobe_executable=args.ffprobe_executable)
        if result['status']=='passed':result['independent_v3_audit']=verify_v3_projection(workspace)
        result['protected_originals']=verify_protected(args.experiment_root)
        write_json(args.experiment_root/args.result_name,result)
        if result['status']!='passed':print(json.dumps(result,ensure_ascii=False));return 1
    if args.compare:
        result['comparison']=compare_four(build_asset_workspace(ASSET,args.source_root.resolve()),workspace,args.v2_plan,args.reference_plan,args.experiment_root/args.comparison_name)
    if args.review_notes:
        result['review']=join_review(args.experiment_root/args.comparison_name,args.review_notes,args.experiment_root/'preference_checklist.v1.json',args.experiment_root/args.review_name)
    evidence_name=(args.review_name if args.review_notes else args.comparison_name if args.compare else args.preflight_name if args.preflight else args.result_name+'.run')+'.protected_after.json'
    write_json(args.experiment_root/evidence_name,verify_protected(args.experiment_root))
    print(json.dumps({'status':'passed','workspace':str(workspace),'first_status':result.get('first_status'),'second_status':result.get('second_status'),'comparison':result.get('comparison'),'review':result.get('review')},ensure_ascii=False));return 0

if __name__=='__main__':raise SystemExit(main())
