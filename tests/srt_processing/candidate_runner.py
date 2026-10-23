"""Explicit, isolated candidate acceptance/comparison. Never runs upstream stages.

PYTHONPATH=src .venv/bin/python -m tests.srt_processing.candidate_runner --prepare --run --compare
Every result/run path must be new. Existing candidate workspace can only be reused.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from archive_core.application import build_asset_workspace
from archive_core.domain import AssetId
from archive_core.interfaces import SourceAlignmentDTO, reconstruct_sentence_text, normalize_chinese_text

ASSET = AssetId('cnbc', '2000', 'morning')
DEFAULT_SOURCE = Path('output/transcription-integration')
DEFAULT_EXPERIMENT = Path('output/cue-evaluation/20261022-candidate-v2')
DEFAULT_REFERENCE = Path('output/cue-evaluation/20261022-agent-vs-dp/audit/reference_v1/agent_plan.json')
OUTPUT_NAMES = {'subtitle_plan.json','english.srt','chinese.srt','bilingual.srt','srt_processing_report.json','srt_processing_manifest.json'}


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write('\n')


def evidence(path: Path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    stamp = path.stat()
    return {'sha256':h.hexdigest(),'size_bytes':stamp.st_size,'mtime_ns':stamp.st_mtime_ns}


def snapshot(root: Path):
    return {str(path.relative_to(root)):evidence(path) for path in sorted(root.rglob('*')) if path.is_file()}


def verify_protected(experiment: Path):
    protected = read_json(experiment/'protected_before.v1.json')
    result = {}
    for name, saved in protected.items():
        now = snapshot(Path(saved['root']))
        differences = {key:{'before':saved['files'].get(key),'after':now.get(key)}
                       for key in sorted(set(saved['files']) | set(now)) if saved['files'].get(key) != now.get(key)}
        result[name] = {'unchanged':not differences,'file_count':len(now),'differences':differences}
    if not all(row['unchanged'] for row in result.values()):
        raise ValueError(f'protected original files changed: {result}')
    return result


def prepare_candidate_workspace(source_root: Path, output_root: Path, asset: AssetId = ASSET):
    """Copy small upstream artifacts, rebase manifest paths only, link media read-only in use.

    Source bytes/mtime are never changed. No permissions are changed on media links.
    Derived transcription manifest path rebasing is explicit, not upstream regeneration.
    """
    source = build_asset_workspace(asset, source_root.resolve())
    target = build_asset_workspace(asset, output_root.resolve())
    required = ('source_alignment.json','translation_result.json','translation_manifest.json','transcription_manifest.json','video.mp4','audio.wav')
    missing = [name for name in required if not (source/name).is_file()]
    if missing:
        raise ValueError(f'missing existing upstream artifacts: {missing}')
    if target.exists():
        raise FileExistsError(f'refusing to overwrite candidate workspace {target}')
    before = snapshot(source)
    target.mkdir(parents=True)
    copied = []
    for path in sorted(source.iterdir()):
        if not path.is_file() or path.name in OUTPUT_NAMES or path.name in ('audio.wav','video.mp4','transcription_manifest.json'):
            continue
        with path.open('rb') as src, (target/path.name).open('xb') as dst:
            shutil.copyfileobj(src,dst)
        copied.append(path.name)
    for name in ('video.mp4','audio.wav'):
        (target/name).symlink_to(source/name)
    manifest = read_json(source/'transcription_manifest.json')
    rebased = []
    for name, row in manifest['records'].items():
        old = row['path']
        new = str(target/Path(old).name)
        if not (target/Path(old).name).is_file():
            raise ValueError(f'no copied/linked artifact for transcription record {name}')
        row['path'] = new
        rebased.append({'record':name,'original':old,'candidate':new})
    write_json(target/'transcription_manifest.json',manifest)
    assert before == snapshot(source), 'preparation changed original source'
    return {'source_workspace':str(source),'candidate_workspace':str(target),
            'copied_small_upstream':copied,'media_links':{name:str((target/name).readlink()) for name in ('video.mp4','audio.wav')},
            'media_access':'read-only usage; no chmod or write through links',
            'derived_transcription_manifest':{'source':evidence(source/'transcription_manifest.json'),'candidate':evidence(target/'transcription_manifest.json'),'path_rebases_only':rebased},
            'source_unchanged':True}


def inspect_cues(cues, alignment, translation):
    """Audit already-fixed cuts under candidate counts/layout; never chooses a cue boundary."""
    from srt_processing.domain.rules import chinese_half_units, english_characters, wrap_english_text
    from srt_processing.domain.boundaries import hard_chinese_boundaries
    chinese = {row.sentence_id:normalize_chinese_text(row.translated_text) for row in translation.sentence_translations}
    sentences = {row.id:row for row in alignment.sentences}
    word_cursor = 0
    chinese_cursors = {sid:0 for sid in chinese}
    records = []
    for cue in cues:
        issues=[]
        try:
            wrapped=wrap_english_text(cue['english_text'])
            lines=wrapped.split('\n')
            if not 1 <= len(lines) <= 2 or any(english_characters(line)>42 for line in lines):
                raise ValueError('wrapper violated 2x42')
            layout_error=None
        except ValueError as error:
            lines=[];layout_error=str(error);issues.append('english_2x42_not_packable')
        if len(lines)==2:
            first_word=int(cue['fragments'][0]['first_word_id'][1:])-1
            last_word=int(cue['fragments'][-1]['last_word_id'][1:])
            allowed_prefixes={reconstruct_sentence_text(alignment.words[first_word:end]) for end in range(first_word+1,last_word)}
            if lines[0] not in allowed_prefixes:
                issues.append('english_line_break_not_source_word_boundary')
        units=chinese_half_units(cue['chinese_text'])
        if units>32: issues.append('chinese_word_count_gt16')
        if '\n' in cue['chinese_text']: issues.append('chinese_more_than_one_line')
        if cue['end_ms']-cue['start_ms']>7000: issues.append('duration_gt7000')
        if cue['start_ms'] != alignment.words[int(cue['fragments'][0]['first_word_id'][1:])-1].start_ms:
            issues.append('source_start_anchor')
        merge_needs=[];merge_gaps=[]
        for f in cue['fragments']:
            sid=f['sentence_id'];first=int(f['first_word_id'][1:])-1;end=int(f['last_word_id'][1:])
            assert first==word_cursor,'source word coverage is not contiguous exactly once'
            assert f['chinese_start_offset']==chinese_cursors[sid], 'Chinese cursor gap/overlap'
            zstart,zend=f['chinese_start_offset'],f['chinese_end_offset']
            if zend not in hard_chinese_boundaries(chinese[sid]) and 'hard_chinese_token_boundary' not in issues:
                issues.append('hard_chinese_token_boundary')
            assert zstart<zend<=len(chinese[sid]) and first<end
            assert (end==int(sentences[sid].last_word_id[1:])) == (zend==len(chinese[sid])), 'sentence endpoints differ'
            assert f['speaker_label']==sentences[sid].speaker_label, 'speaker/null not preserved'
            duration=alignment.words[end-1].end_ms-alignment.words[first].start_ms
            zcount=chinese_half_units(chinese[sid][zstart:zend])
            merge_needs.append(duration<834 or 500*zcount>9*duration)
            word_cursor=end;chinese_cursors[sid]=zend
        for left,right in zip(cue['fragments'],cue['fragments'][1:]):
            ls,rs=sentences[left['sentence_id']],sentences[right['sentence_id']]
            merge_gaps.append(alignment.words[int(rs.first_word_id[1:])-1].start_ms-alignment.words[int(ls.last_word_id[1:])-1].end_ms)
        if len(cue['fragments'])>1 and (any(g>=500 for g in merge_gaps) or not any(merge_needs)):
            issues.append('candidate_count_merge_qualification')
        duration=cue['end_ms']-cue['start_ms'];en=english_characters(cue['english_text'])
        records.append({'cue_id':cue['id'],'chinese_word_units':units/2,'english_nonspace_characters':en,
                        'english_lines':lines,'english_line_counts':[english_characters(line) for line in lines],
                        'english_layout_error':layout_error,'hard_compatible_candidate_profile':not issues,'hard_issues':issues,
                        'duration_ms':duration,'chinese_cps_candidate_word_count':round(500*units/duration,6),
                        'chinese_cps_gt9':500*units>9*duration,'english_cps':round(1000*en/duration,6),'english_cps_gt17':1000*en>17*duration})
    assert word_cursor==len(alignment.words)
    assert all(chinese_cursors[sid]==len(text) for sid,text in chinese.items())
    return records


def verify_candidate_projection(workspace: Path):
    import pysubs2
    from archive_core.interfaces import SubtitlePlanDTO, TranslationResultDTO
    from srt_processing.domain.rules import wrap_english_text
    plan=SubtitlePlanDTO.from_dict(read_json(workspace/'subtitle_plan.json'))
    alignment=SourceAlignmentDTO.from_dict(read_json(workspace/'source_alignment.json'))
    translation=TranslationResultDTO.from_dict(read_json(workspace/'translation_result.json'))
    plan.validate_against_inputs(alignment,translation)
    records=inspect_cues([c.to_dict() for c in plan.cues],alignment,translation)
    assert all(row['hard_compatible_candidate_profile'] for row in records), 'candidate violates new capacity/layout'
    for language in ('english','chinese','bilingual'):
        data=(workspace/f'{language}.srt').read_bytes()
        assert not data.startswith(b'\xef\xbb\xbf') and b'\r' not in data and data.endswith(b'\n')
        subs=pysubs2.SSAFile.from_string(data.decode('utf-8'),format_='srt')
        assert len(subs)==len(plan.cues)
        for event,cue in zip(subs,plan.cues,strict=True):
            en=wrap_english_text(cue.english_text)
            expected=en if language=='english' else cue.chinese_text if language=='chinese' else cue.chinese_text+'\n'+en
            assert (event.start,event.end,event.plaintext)==(cue.start_ms,cue.end_ms,expected)
            assert len(event.plaintext.split('\n')) <= (2 if language=='english' else 1 if language=='chinese' else 3)
    return {'plan_input_cross_validation':True,'source_words_exactly_once':len(alignment.words),'sentences':len(alignment.sentences),
            'normalized_chinese_codepoints_exactly_once':sum(len(normalize_chinese_text(s.translated_text)) for s in translation.sentence_translations),
            'three_srt_independent_readback':True,'candidate_profile_all_cues_compatible':True,'cue_metrics':records}


def compare_three(source: Path, candidate: Path, reference_path: Path, out: Path):
    from archive_core.interfaces import TranslationResultDTO
    from srt_processing.domain.rules import PROFILE
    alignment=SourceAlignmentDTO.from_dict(read_json(source/'source_alignment.json'))
    translation=TranslationResultDTO.from_dict(read_json(source/'translation_result.json'))
    plans={'old242':read_json(source/'subtitle_plan.json'),'candidate':read_json(candidate/'subtitle_plan.json'),'agent153':read_json(reference_path)}
    metrics={name:inspect_cues(plan['cues'],alignment,translation) for name,plan in plans.items()}
    lookup={name:{r['cue_id']:r for r in rows} for name,rows in metrics.items()}
    parent={s.id:s.id for s in alignment.sentences}
    def root(sid):
        while parent[sid]!=sid: sid=parent[sid]
        return sid
    for plan in plans.values():
        for cue in plan['cues']:
            sids=[f['sentence_id'] for f in cue['fragments']]
            for sid in sids[1:]:parent[root(sid)]=root(sids[0])
    groups={}
    for sid in parent:groups.setdefault(root(sid),[]).append(sid)
    rows=[]
    for sentence in alignment.sentences:
        sid=sentence.id;row={'sentence_id':sid,'source_english':sentence.text,'chinese':next(s.translated_text for s in translation.sentence_translations if s.sentence_id==sid)}
        row['comparison_group_sentence_ids']=groups[root(sid)]
        for name,plan in plans.items():
            cues=[dict(c,**{'candidate_profile_audit':lookup[name][c['id']]}) for c in plan['cues'] if any(f['sentence_id']==sid for f in c['fragments'])]
            row[name]=cues
            all_group=[c for c in plan['cues'] if any(f['sentence_id'] in row['comparison_group_sentence_ids'] for f in c['fragments'])]
            row[name+'_complete_group_compatible_candidate_profile']=all(lookup[name][c['id']]['hard_compatible_candidate_profile'] for c in all_group)
        signature=lambda name:[[(f['sentence_id'],f['first_word_id'],f['last_word_id'],f['chinese_start_offset'],f['chinese_end_offset']) for f in c['fragments']] for c in row[name]]
        row['candidate_same_cuts_as_agent153']=signature('candidate')==signature('agent153')
        row['candidate_same_cuts_as_old242']=signature('candidate')==signature('old242')
        cuts=lambda name:{(c['fragments'][-1]['last_word_id'],c['fragments'][-1]['chinese_end_offset']) for c in row[name] if c['fragments'][-1]['sentence_id']==sid and c['fragments'][-1]['last_word_id']!=sentence.last_word_id}
        row['structural_cut_similarity_only_not_semantic']={'old_shared_agent_internal_cuts':len(cuts('old242') & cuts('agent153')),'candidate_shared_agent_internal_cuts':len(cuts('candidate') & cuts('agent153')),'old_agent_symmetric_difference':len(cuts('old242') ^ cuts('agent153')),'candidate_agent_symmetric_difference':len(cuts('candidate') ^ cuts('agent153'))}
        rows.append(row)
    out.mkdir()
    write_json(out/'three_way_metrics.json',{'method':'fixed-cut audit with candidate word count/2x42; original agent times and cuts unchanged',
        'historical_old_native_metrics_path':'output/cue-evaluation/20261022-agent-vs-dp/audit/comparison_metrics.v2.json',
        'candidate_profile_parameters':PROFILE.to_dict(),'profiles':{name:plan.get('rules',plan.get('method')) for name,plan in plans.items()},'cue_metrics':metrics,
        'summary':{name:{'cue_count':len(items),'hard_incompatible_candidate_profile':sum(not r['hard_compatible_candidate_profile'] for r in items),
                       'chinese_word_count_gt16':sum('chinese_word_count_gt16' in r['hard_issues'] for r in items),
                       'english_2x42_not_packable':sum('english_2x42_not_packable' in r['hard_issues'] for r in items),
                       'hard_chinese_token_boundary_cues':sum('hard_chinese_token_boundary' in r['hard_issues'] for r in items),
                       'merge_qualification_incompatible':sum('candidate_count_merge_qualification' in r['hard_issues'] for r in items),
                       'too_short':sum(r['duration_ms']<834 for r in items),'chinese_cps_gt9_candidate_count':sum(r['chinese_cps_gt9'] for r in items),'english_cps_gt17':sum(r['english_cps_gt17'] for r in items)} for name,items in metrics.items()}})
    with (out/'three_way_sentences.jsonl').open('x',encoding='utf-8') as stream:
        for row in rows:stream.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n')
    with (out/'three_way_view.txt').open('x',encoding='utf-8') as stream:
        for row in rows:
            stream.write('\n'+row['sentence_id']+': '+row['source_english']+'\nZH: '+row['chinese']+'\n')
            for name in plans:
                stream.write(name.upper()+' group-compatible='+str(row[name+'_complete_group_compatible_candidate_profile'])+'\n')
                for c in row[name]:
                    stream.write(f'  {c["id"]} {c["start_ms"]}..{c["end_ms"]} '+str([(f['first_word_id'],f['last_word_id'],f['chinese_start_offset'],f['chinese_end_offset']) for f in c['fragments']])+f'\n    {c["english_text"]} || {c["chinese_text"]}\n    lines='+repr(c['candidate_profile_audit']['english_lines'])+' issues='+str(c['candidate_profile_audit']['hard_issues'])+'\n')
    return {'sentences':len(rows),'candidate_same_cuts_as_agent153':sum(r['candidate_same_cuts_as_agent153'] for r in rows),'candidate_same_cuts_as_old242':sum(r['candidate_same_cuts_as_old242'] for r in rows)}



def join_manual_review(comparison: Path, notes_path: Path, out: Path):
    """Join all explicitly hand-written judgments; never infer semantic verdicts."""
    rows=[json.loads(line) for line in (comparison/'three_way_sentences.jsonl').read_text().splitlines()]
    notes=[json.loads(line) for line in notes_path.read_text().splitlines() if line.strip()]
    by_sid={note['sentence_id']:note for note in notes}
    assert len(by_sid)==len(notes)==len(rows), 'manual review must cover each sentence exactly once'
    assert set(by_sid)=={row['sentence_id'] for row in rows}
    out.mkdir()
    counts={'candidate_vs_old':{},'candidate_vs_agent':{}}
    with (out/'all_sentences.md').open('x',encoding='utf-8') as md, (out/'all_sentences.jsonl').open('x',encoding='utf-8') as js, (out/'all_sentences.tsv').open('x',encoding='utf-8') as tsv:
        md.write('# 全量三方cue文本审读\n\n所有优/平/劣为agent逐句文本审读，不是自动语义评分、音画或出版验收。候选与参考容量差异和关联组同时披露；`↵`代表真实英文行分隔，坐标是各句原文codepoint offset。\n')
        tsv.write('sentence_id\tcandidate_vs_old\tcandidate_vs_agent\treason\tresidual\n')
        for row in rows:
            note=by_sid[row['sentence_id']]
            for key in counts:
                assert note[key] in ('优','平','劣')
                counts[key][note[key]]=counts[key].get(note[key],0)+1
            row['manual_review']=note
            js.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n')
            tsv.write('\t'.join([row['sentence_id'],note['candidate_vs_old'],note['candidate_vs_agent'],note['reason'],note['residual']])+'\n')
            md.write('\n## '+row['sentence_id']+' · 候选vs旧 '+note['candidate_vs_old']+' / vs参考 '+note['candidate_vs_agent']+'\n\n')
            md.write('**英文源句**：'+row['source_english']+'\n\n**完整中文**：'+row['chinese']+'\n\n')
            md.write('**差异原因**：'+note['reason']+'\n\n**残余/代价**：'+note['residual']+'\n\n')
            md.write('关联句组：'+', '.join(row['comparison_group_sentence_ids'])+'；同参考断点='+str(row['candidate_same_cuts_as_agent153'])+'；同旧断点='+str(row['candidate_same_cuts_as_old242'])+'。\n')
            for name,title in [('old242','旧242'),('candidate','新候选'),('agent153','原153参考（未改断点/时间）')]:
                md.write('\n### '+title+' · 完整组v2硬兼容='+str(row[name+'_complete_group_compatible_candidate_profile'])+'\n')
                for cue in row[name]:
                    audit=cue['candidate_profile_audit']
                    md.write('\n- **'+cue['id']+'** '+str(cue['start_ms'])+'–'+str(cue['end_ms'])+'ms；'+str([(f['sentence_id'],f['first_word_id'],f['last_word_id'],f['chinese_start_offset'],f['chinese_end_offset']) for f in cue['fragments']])+'\n')
                    md.write('  - 中文：'+cue['chinese_text']+'\n')
                    md.write('  - 英文逻辑正文：'+cue['english_text']+'\n')
                    md.write('  - 英文v2行：'+(' ↵ '.join(audit['english_lines']) if audit['english_lines'] else '**不可排** '+str(audit['english_layout_error']))+'\n')
                    md.write('  - 中文word计数='+str(audit['chinese_word_units'])+'；英文行计数='+str(audit['english_line_counts'])+'；硬问题='+str(audit['hard_issues'])+'\n')
    write_json(out/'summary.json',{'reviewed_sentences':len(rows),'manual_verdict_counts':counts,'notes_evidence':evidence(notes_path),'method':'full-text agent review, no automatic semantic scoring'})
    return {'reviewed_sentences':len(rows),'manual_verdict_counts':counts}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare',action='store_true');parser.add_argument('--run',action='store_true');parser.add_argument('--compare',action='store_true')
    parser.add_argument('--source-root',type=Path,default=DEFAULT_SOURCE);parser.add_argument('--experiment-root',type=Path,default=DEFAULT_EXPERIMENT)
    parser.add_argument('--reference-plan',type=Path,default=DEFAULT_REFERENCE);parser.add_argument('--result-name',default='workflow.v1.json')
    parser.add_argument('--review-notes',type=Path);parser.add_argument('--review-name',default='review_v1')
    parser.add_argument('--comparison-name',default='comparison_v1');parser.add_argument('--ffprobe-executable',default='ffprobe')
    args=parser.parse_args(argv)
    if not any((args.prepare,args.run,args.compare,args.review_notes)):
        print(json.dumps({'status':'opt_in_required'}));return 2
    args.experiment_root.mkdir(parents=True,exist_ok=True)
    output_root=args.experiment_root.resolve()/'workspaces'
    if args.prepare:
        write_json(args.experiment_root/'preparation.v1.json',prepare_candidate_workspace(args.source_root,output_root))
    result={}
    if args.run:
        from tests.srt_processing.sample_runner import run_local_sample
        result=run_local_sample(output_root=str(output_root),ffprobe_executable=args.ffprobe_executable)
        if result['status']=='passed':
            result['independent_candidate_projection_audit']=verify_candidate_projection(build_asset_workspace(ASSET,output_root))
        result['protected_originals']=verify_protected(args.experiment_root)
        write_json(args.experiment_root/args.result_name,result)
        if result['status']!='passed':print(json.dumps(result,ensure_ascii=False));return 1
    if args.compare:
        result['comparison']=compare_three(build_asset_workspace(ASSET,args.source_root.resolve()),build_asset_workspace(ASSET,output_root),args.reference_plan,args.experiment_root/args.comparison_name)
        write_json(args.experiment_root/(args.comparison_name+'.protected_after.json'),verify_protected(args.experiment_root))
    if args.review_notes:
        result['manual_review']=join_manual_review(args.experiment_root/args.comparison_name,args.review_notes,args.experiment_root/args.review_name)
        write_json(args.experiment_root/(args.review_name+'.protected_after.json'),verify_protected(args.experiment_root))
    print(json.dumps({'status':'passed','workspace':str(build_asset_workspace(ASSET,output_root)),'first_status':result.get('first_status'),'second_status':result.get('second_status'),'comparison':result.get('comparison')},ensure_ascii=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
