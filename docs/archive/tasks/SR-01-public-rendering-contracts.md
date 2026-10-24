# SR-01 — 公共 rendering 工件与严格契约

- **Status:** accepted
- **Owner:** render_contracts 子开发 agent（负责人验收）
- **Depends on:** 无
- **Depended on by:** SR-02、SR-03、SR-04、SR-05

## 范围

阅读archive_core/rendering指南及ADR-0006第6–8、17–19节。新增四个ArtifactType和规范名，沿用RENDERED_VIDEO；新增公共profile、媒体/font/tool identity、逐cue视觉断点、render plan/report/成功manifest DTO及显式严格序列化。字段要足够支撑ADR全部证据/复用/像素QA，不把整个规范藏入无约束dict。不改既有subtitle contract形状。

冻结下游可用接口：plan按公共SubtitlePlanDTO正文和code-point offset重建视觉行，严格验证时间/正文hash/顺序/断点/行数/范围；profile确定性hash；manifest固定三项直接输入、四项正文输出证据并交叉校验。只做公共机械契约，不把布局搜索搬进archive_core。

## 验证/交接

新增契约测试覆盖round-trip、未知/缺失/额外字段、bool伪整数、非有限数、schema、规范路径/hash/size、ID时间/offset、report/manifest摘要一致、确定性hash、已有契约不回归。开发者跑定向及完整离线pytest。先交接口与字段清单给负责人，确认后编码；完成后交文件清单/命令/结果，由负责人复验。

## 字段/API 交接（负责人已批准设计，已实现待验收）

新增 `archive_core.interfaces.rendering`，并从公共 `archive_core.interfaces` 导出。现有
`SubtitleArtifactEvidenceDTO` 的文件名白名单拒绝新的 rendering 工件，故不修改旧契约，新增
同形的 `RenderArtifactEvidenceDTO(path, size_bytes, sha256)`；只接受本阶段三份直接输入和四份
正文输出的规范文件名。四个新 `ArtifactType` 严格按 ADR 第 8 节命名，沿用 `RENDERED_VIDEO`。

### 严格值对象

- `RenderFontSpecDTO(path, sha256, family, style, face_index)`；精确绝对路径，无系统字体搜索。
- `RenderFontIdentityDTO(spec, size_bytes, measurement_adapter_version, postscript_name)`；测量 adapter 版本串必须
  包含其实际 Pillow/FreeType 依赖版本，不只写一个未绑定运行库的自定义版本号。
- `RenderTextStyleDTO(font_size, primary_color)`。
- `RenderEncoderDTO(video_codec, crf, preset, pixel_format, audio_mode, movflags)`。
- `RenderStreamMappingDTO(video_selector, audio_selector, fps_mode, map_metadata, map_chapters,
  include_subtitles, include_data)`：负责人批准追加，严格固定 ADR 的主视频/全部音频、passthrough、
  metadata/chapters保留和无字幕/data流语义，由plan显式保存，不能藏在无版本argv实现里。
- `RenderProfileDTO`：ADR 第 9 节的全部显式字段、`font/chinese/english/encoder` 以上述 DTO
  嵌套。额外固定 `version/layout_version` 以标识算法。`sha256` 属性对完整显式 `to_dict()` 的
  UTF-8、非 ASCII 不转义、排序 key、紧凑 JSON 做 SHA-256，不保存执行时间和临时路径。
- `RenderToolsDTO(pysubs2_version, ffmpeg_version, ffprobe_version, libass_version, libx264_version)`。
- `RenderTagDTO(key, value)`；tags 是无重复 key 的有序 tuple，不接受无约束 JSON。
- `RenderChapterDTO(id, start_us, end_us, tags)`。
- `RenderVideoStreamDTO(index, codec_name, width, height, sar_numerator, sar_denominator,
  dar_numerator, dar_denominator, fps_numerator, fps_denominator, r_fps_numerator,
  r_fps_denominator, start_time_us, duration_us, frame_count, pixel_format, rotation_degrees, tags)`。
- `RenderAudioStreamDTO(index, codec_name, sample_rate, channels, channel_layout, start_time_us,
  duration_us, default, tags)`；音频 duration 可空，不假造不可得的流时长。
- `RenderMediaDTO(format_name, duration_us, start_time_us, video, audio_streams, video_stream_count,
  subtitle_stream_count, data_stream_count, tags, chapters)`。探测数字由 adapter 以 Decimal 读取并
  转为整数微秒，不能先 float 再截断为毫秒。一帧容差使用 rational FPS 运算；`r_fps==fps` 不
  证明 CFR，可靠 VFR 判断由 probe adapter 完成，否则按 ADR 受控失败。
- `RenderBoundsDTO(left, top, right, bottom)`、`RenderLineMetricsDTO(width, height)`：只接受有限
  非负测量值，非空矩形/正高度；bool 不得冒充数值。
- `RenderScaledStyleDTO` 保存实际 PlayRes、缩放后的 margin/字号/描边/阴影和四行限制；
  安全区域另存为 typed bounds，profile 与实际缩放的一致性由 rendering domain 重算。

媒体保留源关键 metadata（例如 title/comment/language）、全部 chapter 时间和内容、音频
default/language/title；输出不得要求 encoder tag 与输入相同。完整原始 probe JSON 如需审计，
留在 adapter 诊断，不替代这些公共严格字段，也不扩成通用媒体框架。

### Plan

`SubtitleRenderPlanDTO(asset_id, inputs, input_media, profile, profile_sha256, font, tools,
ass_serialization_version, scaled_style, safe_area, cues, schema_version)`：

- `inputs` 固定且仅含 `srt_processing_manifest/subtitle_plan/video` 的 typed evidence；禁止任意
  路径、缺项或多项。asset ID 使用公共 `AssetId` 机械验证。
- `stream_mapping` 固定上述映射 DTO；`ass_serialization_version=bilingual-ass.word-joiner.v1`
  和 `ass_timing_policy=nearest-centisecond-half-up.v1` 精确绑定本轮用户批准的两项投影策略。
- `RenderCueDTO(id, start_ms, end_ms, chinese_text_sha256, english_text_sha256,
  chinese_break_offsets, english_break_offsets, chinese_lines, english_lines, expected_bounds)`。
  两个 lines 字段是 `RenderLineMetricsDTO` tuple，数量必须为 offset 数加一，每语言 1～2 行，
  合计最多 4 行。断点为正文 Unicode code point 间的严格递增内部 offset。
- `validate_against_subtitle_plan(source)` 校验 `c1..cN` 顺序/数目、原时间、视频 fingerprint、
  两份逻辑正文 hash、offset 范围和正文重建。原始行通过 offset 对权威正文切片，拼回后必须
  字符完全一致，不从 SRT 恢复；行首/行尾空白不在公共契约里静默删除。
- grapheme、词间边界、标点与纯布局搜索属于 rendering domain；公共 DTO 只做机械保真验证。

**用户已批准（ADR 第 12.1 节）：** 原始毫秒作为不可变权威，ASS 最近 10ms round-half-up
投影且每边绝对误差不超过 5ms。cue 显式新增
`ass_start_ms/ass_end_ms/start_delta_ms/end_delta_ms`，plan记录
`ass_timing_policy=nearest-centisecond-half-up.v1`；验证量化一致、正时长、不重叠、不越界。
ASS round-trip 与投影时间比较，不谎称原毫秒无损。

### Report 与 Manifest

- `RenderFindingDTO(code, severity, cue_id, start_ms, end_ms, observed_width, observed_height,
  bounds, diagnostic)`；cue/time/measurement 可空且成对时间必须一致，diagnostic 最多 2048 字符。
- `RenderPixelResultDTO(cue_id, time_ms, bounds, line_count, font_identity_matches, styles_match)`。
- `RenderSummaryDTO(cue_count, chinese_line_counts, english_line_counts, four_line_cue_count,
  maximum_width, maximum_height, warning_count, error_count, font_glyph_passed,
  ass_round_trip_passed, pixel_preflight_passed, output_media_passed)`；两项 line_counts 为固定两槽
  tuple，分别表示一行和两行 cue 数，合计等于 cue_count。
- `SubtitleRenderReportDTO(asset_id, status, summary, findings, pixel_results, error_category,
  schema_version)`；成功必须无错误、完整逐 cue 像素记录且全部 QA 为真，失败类别只接受
  ADR 第 19 节的稳定枚举，不把任意异常暴露为公共错误。
- `SubtitleRenderManifestDTO(asset_id, status, completed_at, inputs, profile, profile_sha256,
  font, tools, input_media, output_media, outputs, summary, schema_version)`；只允许 succeeded，
  UTC ISO 8601 完成时间，固定三输入和 `plan/ass/video/report` 四输出 evidence。
  `validate_against_plan_and_report(plan, report)` 交叉验证身份、profile hash、字体、tools、
  输入证据和媒体、cue 数及与 report 完全一致的 summary；文件实际 hash/size 由 store 验证。

所有 DTO 显式严格 `to_dict()/from_dict()`，未知/缺失/额外字段、未知 schema、bool 伪整数、
NaN/Infinity、非法 hash/path/offset 均失败；容器冻结，反序列化不隐式 str/int 转型。下游适配器
只依赖上述公共接口；不触碰现有 subtitle DTO 形状，不由本任务实现布局/FFmpeg/文件写入。

## 开发交付与验证（2026-10-24 00:00 CST，尚待负责人验收）

已实现文件：`src/archive_core/domain/artifacts.py`、
`src/archive_core/interfaces/rendering.py`、`src/archive_core/interfaces/__init__.py`，
新增 `tests/archive_core/test_rendering_contracts.py`，同步本模块指南。本任务未修改上游合同形状，
未调用字体、FFmpeg、provider、ASR 或修改 output，未提交 Git commit。

```text
.venv/bin/python -m pytest tests/archive_core/test_rendering_contracts.py -q
188 passed

.venv/bin/python -m pytest tests/archive_core/test_rendering_contracts.py \
  tests/archive_core/test_subtitle_contracts.py tests/archive_core/test_archive_core_contracts.py -q
344 passed

.venv/bin/python -m pytest tests/ -q
1592 passed, 5 skipped
```

覆盖全部嵌套 DTO 缺失/额外字段和 JSON round-trip，未知 schema，bool伪整数、NaN/Infinity，
证据规范路径/hash/size，毫秒到百分秒half-up与塌缩/越界，原正文和时间保真，profile重签后缩放
突变、report重签后像素/摘要突变、manifest/report/plan身份交叉校验。首次定向出现一项测试
构造非法源正文（leading whitespace）的问题，已证明原公共源DTO会先拒绝该输入，改为同时验证
此源门禁与合法内置词间空白的无损保留，未放宽生产校验。

负责人须独立复验并将状态改为 accepted；开发 agent 不自行签字。

## 负责人验收（2026-10-24）

已审公共类型、完整证据、版本化identity、profile缩放、原文/原时间与ASS投影守恒、成功report/manifest交叉验证和重签反例。独立复验定向188 passed、完整1592 passed / 5 skipped（6.05s），diff check通过。SR-01 accepted，放行SR-02；不代表rendering模块或样片完成。
