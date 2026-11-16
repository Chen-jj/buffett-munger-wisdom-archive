# NB-01 公共契约与转录编辑标记

> 2026-11-17归档说明：公共契约/编辑标记技术切片已交付，并由后续NB-08真实链路验收接续；原待验头部和过程结果保留。 原路径`docs/tasks/NB-01-contracts.md`；原状态、历史不commit/push约束及验证结果属于当时记录。后续入口：[NB-12](../../tasks/NB-12-chunking-quality-iteration.md) / [ADR-0013](../../decisions/0013-typed-chunking-quality-and-regression.md)。

状态：工程接口冻结，实施中（2026-11-05 Asia/Shanghai）。依据 ADR-0008～0012；不增加兼容路径。

## 新公共接口：archive_core.interfaces.bilingual

所有 DTO frozen dataclass，显式 `to_dict/from_dict` 严格拒绝额外/缺失字段、错误类型/版本。
文件暂存开发期间旧类尚未切换；最终下游直接消费 FinalBilingualDraftDTO，旧契约不作为生产路径保留。

- `ArtifactEvidenceDTO(path: str, size_bytes: int, sha256: str)`；路径为绝对规范路径。
- `MediaBoundaryDTO(video_sha256: str, duration_ms: int, frame_timestamps_us: tuple[int,...] | None)`；实际解码帧 PTS，缺失用null，不用平均帧率冒充。公共工件 `media_boundary.json`。
- `ProtectedSpanDTO(first_word_id, last_word_id, reason)`；已识别且不可内部断开。
- `ReadingBudgetDTO(base_units: int, maximum_units: int, extension_ms: int, chinese_line_target_units: int=16, counting_version: str='unicode14-latin-word.v2')`；预算只读。
- `SourceChunkDTO(id: str='k1..kN', word_ids: tuple[str,...], sentence_ids: tuple[str,...], english_text: str, start_ms: int, base_end_ms: int, budget: ReadingBudgetDTO, issues: tuple[str,...])`；英文字符/时长/CPS可由正文锚点精确推导，无浮点权威字段。
- `SourceChunkPlanDTO(asset_id: str, source_alignment_sha256: str, media: MediaBoundaryDTO, policy: dict, analyzer: dict, chunks: tuple[SourceChunkDTO,...], protected_spans: tuple[ProtectedSpanDTO,...], analyzed_sentence_ids: tuple[str,...])`；schema `subtitle.source-chunks.v1`，`validate_against_alignment(alignment)` 验证完整词覆盖、正文、时间、句归属/section/speaker。
- `ChunkTranslationDTO(id, translated_text)`；`ChunkTranslationResultDTO(asset_id, source_alignment_sha256, source_chunks_sha256, chunks: tuple[ChunkTranslationDTO,...], section_titles: tuple[SectionTitleTranslationDTO,...])`；schema `translation.chunks.v1`；`validate_against_inputs(alignment, chunks)`。
- `FinalCueDTO(id: 'c1..cN', word_ids, sentence_ids, english_text, chinese_text, start_ms, base_end_ms, final_end_ms, initial_chunk_ids)`；`end_ms` property=final_end_ms，`extension_ms` property=final_end-base_end。
- `FinalBilingualDraftDTO(asset_id, source_alignment_sha256, source_chunks_sha256, translation_result_sha256, media, policy: dict, cues: tuple[FinalCueDTO,...], section_titles, diagnostics: tuple[dict,...])`；schema `subtitle.final-draft.v1`；`validate_against_inputs(alignment, source_chunks, translation)` 校验词覆盖/来源/正文/锚点/初译来源，但不要求中文为初译字符切片。指标超标不由DTO阻断；源越界/实际重叠硬拒绝。
- `StageManifestDTO(stage: str, asset_id: str, inputs: dict[str,ArtifactEvidenceDTO], outputs: dict[str,ArtifactEvidenceDTO], identity: dict, completed_at: str, execution: dict[str,int])`；schema `pipeline.stage-manifest.v1`；只描述成功，固定status=succeeded。stage由当前枚举校验。阶段业务入口负责输入输出key集合与内容互验，公共DTO做严格证据/有限identity/计数。

规范工件新增：source_chunks.json / source_chunking_report.json / source_chunking_manifest.json / final_bilingual_draft.json / bilingual_postprocessing_report.json / bilingual_postprocessing_manifest.json / media_boundary.json / acquisition_receipt.json。
初译沿用 translation_result.json/translation_manifest.json 但替换schema与DTO，不保留旧解析。
运行路径 `build_pipeline_run_path(asset_id, root, run_id)` → workspace/pipeline_runs/<run_id>；run_id只允许字母数字、下划线和连字符，不创目录。

## 转录标记

SourceAlignmentDTO 唯一schema变为 transcription.source-alignment.v2，新增必需序列化字段 `annotations`。
`EditorialBreakDTO(id='e1..eN', after_word_id, official_token_ids, source='cnbc', kind='editorial_break', policy_version='cnbc-editorial-break.v1')`，无发音时间。位置及来源token必须与对应word一致。
处理仅在融合后canonical发布之前；source asset明确为cnbc且matched官方token含U+2014时移除word正文对应U+2014；保持ID/顺序/时间/来源。sentence从投影后的words重建。缓存只令canonical句阶段失效，不令ASR失效。

## 验证

新增纯contract roundtrip/unknown字段/来源/词覆盖/时间/非重叠测试；编辑破折号来源、非目标、ASR-only、多个/尾端回归；公共factory不依赖tests且构造不加载模型。

## 开发验证（2026-11-05）

`.venv/bin/python -m pytest tests/archive_core/test_bilingual_contracts.py tests/transcription/ -q`：
325 passed / 1 skipped，1.01s。新增纯契约/编辑标记/工厂构造回归。旧转录3项断言按唯一v2 schema
替换：未知版本由v2改测v1、正常roundtrip预期v2、缺sections从旧数组错误改为严格缺字段错误；
不移除覆盖/来源/时间业务断言。26表面词为合成来源规则回归，不冒称已核本次真实ASR产物。
共享计数/帧函数见`archive_core.interfaces.bilingual_timing`，两帧为空PTS集合
`end_us<=pts<next_start_us`，借时上界取next_start之前倒数第2个PTS向下取整ms。
