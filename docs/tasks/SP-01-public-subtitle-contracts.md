# SP-01 — 公共字幕工件与严格DTO

- **Status:** accepted
- **Owner:** contracts 子开发 agent；仅技术负责人标记accepted
- **Module:** archive_core
- **Decision coverage:** ADR-0003 §5、§10–13、§14.1
- **Depends on:** 无
- **Depended on by:** SP-02、SP-04

## 范围与验收标准

- 新增四个ArtifactType及规范文件名，保留现有english/chinese.srt。发布严格版本化SubtitlePlanDTO及cue/fragment/timing、report/finding、manifest/evidence契约，显式to_dict/from_dict。

- plan保存ADR要求的语言、三个内容hash、媒体/fps/G、profile/算法/文本计数版本、c1..cN、正文、原speaker和字符范围；不含findings/视觉lines/执行时间。

- 提供对公共alignment+translation的交叉校验：源词和规范中文范围按顺序恰好覆盖一次、sentence/section/speaker/时间锚点/正文重建。manifest绑定两条manifest及内容、视频、规则/工具/codec身份和五份输出证据。

- 测试JSON往返、未知版本/字段、bool冒充整数、hash/path、范围缺失/重复/重排/错配、section/speaker/时间错误。更新archive_core指南，并交接精确API。不得改上游DTO。

## 验证与交接

```bash
.venv/bin/python -m pytest tests/archive_core/ -q -m "not live"
.venv/bin/python -m pytest tests/ -q -m "not live"
git diff --check
```

记录实际命令/结果、API与未解决问题，再交负责人复验。先读根与模块AGENTS，保留用户已有ADR/指南修改；不得删除文件/资产，不作无关重构。

## 开发交接（2026-10-21）

实现文件：`src/archive_core/interfaces/subtitles.py`、`subtitle_text.py`，公共入口统一导出。
工件枚举、模块指南及 `tests/archive_core/test_subtitle_contracts.py` 同步更新。未改上游 DTO，
未改 ADR、srt 模块、源资产或正式工件；未作 Git 提交。

### 精确公共 API

- `SubtitleFragmentDTO(sentence_id, first_word_id, last_word_id, chinese_start_offset,
  chinese_end_offset, speaker_label)`：中文为规范化字符的 `[start,end)` 范围。
- `SubtitleTimingAdjustmentDTO(extension_ms, purposes, original_gap_ms, original_gap_class,
  space_source="word_gap")`：purposes 按 `minimum_duration, chinese_cps, gap_closing` 顺序；
  gap class 为 `long_gap / short_gap / preserved_gap / last_cue`，最后一条 gap 为 null。
- `SubtitleCueDTO(id, section_id, start_ms, base_end_ms, end_ms, english_text, chinese_text,
  fragments, timing_adjustment, break_methods, mapping_method="monotonic_proportional.v1")`。
  `break_methods` 非空且限于 `english_sentence/clause/comma/pause/emergency`、
  `chinese_sentence/clause/comma/emergency`（均带对应前缀）以及 `local_rule`。
- `SubtitleMediaDTO(video_duration_ms, audio_duration_ms, usable_duration_ms,
  fps_numerator, fps_denominator, gap_threshold_ms)`：保留原始 fps 分子分母；G 严格向上取整。
- `SubtitleRulesDTO(profile_name, profile_version, profile_sha256, algorithm_version,
  text_normalization_version, character_count_version, boundary_rules_version, cost_rules_version)`。
- `SubtitlePlanDTO(source_alignment_sha256, translation_result_sha256, video_sha256,
  source_language, target_language, media, rules, cues, schema_version=...)`，方法
  `validate_against_inputs(alignment, translation)`。中文 cue 文本由每个源范围去首尾 ASCII
  空格后直接连接，英文由全部引用词 `reconstruct_sentence_text()` 重建。
- `SubtitleProfileDTO(parameters)` 保存严格完整 17 字段参数；`.sha256` 使用 sorted compact
  UTF-8 JSON（`ensure_ascii=False`）。字段与 SP-02 设计一致，含 `pause_boundary_ms`。
- `SubtitleArtifactEvidenceDTO(path, size_bytes, sha256)` 仅允许规范 basename 与正大小。
- `SubtitleProbeDTO(ffprobe_version, stream_selector="v:0",
  show_entries="stream=avg_frame_rate:format=duration")`、`SubtitleCodecDTO()`：后者固定
  pysubs2 1.8.1、SRT、UTF-8、LF、无 BOM、末尾换行、中文在上及毫秒时间格式。
- `SubtitleFindingDTO(code, severity, message, cue_ids=(), sentence_ids=(), word_ids=(),
  original_start_ms=None, original_end_ms=None, final_start_ms=None, final_end_ms=None,
  observed={})`；observed 复制并递归冻结为有限 JSON。
- `SubtitleSummaryDTO(cue_count, merged_cue_count, split_sentence_count, too_short_count,
  chinese_cps_exceeded_count, english_cps_exceeded_count, unclosed_gap_count,
  extended_cue_count, average_frame_rate_approximation_count)`。
- `SrtProcessingReportDTO(asset_id, status, summary, findings, error_code=None,
  schema_version=...)`；失败必须有 error_code，成功不得含 error。
- `SrtProcessingManifestDTO(asset_id, status, completed_at, inputs, rules, profile, media,
  probe, codec, outputs, summary, schema_version=...)`，方法 `validate_against_plan(plan)`。
  inputs 严格键 `transcription_manifest, source_alignment, translation_manifest,
  translation_result, video`；outputs 严格键 `subtitle_plan, english_srt, chinese_srt,
  bilingual_srt, report`。每值为 evidence DTO，映射冻结。
- 全部 DTO 均显式 `to_dict()/from_dict()`，后者拒绝缺失/额外字段及未知 schema。
- `normalize_chinese_text`、`character_boundaries`、`is_combining_mark`、
  `is_layout_whitespace` 使用冻结表，无运行时 Unicode 数据库依赖。

### 实际验证

- `.venv/bin/python -m pytest tests/archive_core/ -q -m "not live"` → **155 passed**。
- `.venv/bin/python -m pytest tests/ -q -m "not live"` → **695 passed, 5 deselected**。
- `git diff --check` → 通过。
- 未运行媒体工具、网络、ASR 或翻译。无未解决阻断。

最后补充的三个反例覆盖跨 section 合并、已知/null/不同已知 speaker 链，以及中文范围切开
组合标记。公共 core 不执行容量/CPS/DP/合并资格业务；这些由后续 SP-02/03 实现和验收。

## 技术负责人验收（2026-10-21）

已审查全部新增DTO、冻结文本规则、工件名、exports及对应反例；未发现阻断。独立复验archive_core **155 passed**，完整离线 **695 passed / 5 deselected**，diff check通过。SP-01验收通过，放行SP-02与SP-04。
