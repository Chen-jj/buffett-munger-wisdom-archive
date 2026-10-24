# SR-05 — 门禁、workflow、复用发布和公共接口

- **Status:** accepted
- **Owner:** workflow_dev 子开发 agent（负责人验收）
- **Depends on:** SR-01、SR-02、SR-03、SR-04 accepted
- **Depended on by:** SR-06

## 范围

拥有rendering/application、interfaces、infrastructure/local.py与composition.py及对应测试。按ADR第6–8、17–19节实现公共command/outcome、整套SRT输入输出证据/公共DTO/词句译文覆盖/视频同源门禁，不import其他功能模块私有代码。workspace唯一用build_asset_workspace。

严格零写dry-run；全套五份成功验证才零写reuse（无clock/像素预检/编码）；部分/损坏/identity变化artifact_conflict；显式overwrite只换本阶段。same-filesystem staging、逐项验证与manifest-last；失败残留保留报告，不删除；failed report不可覆盖既有成功工件，诊断有上限且不能掩盖原错。

## 验证/交接

fake端口测试所有上游链破损/混代/路径/身份，planned/render、planned/reuse、succeeded/reused、overwrite、无clock/0写、逐发布故障、异常分类/公共脱敏文案。生产composition严格配置显式组装，默认测试无真实工具。定向和完整离线套件后负责人复验。

## 前序只读设计交接（历史记录；当前实现交付见文末）

已读 ADR、公共 rendering/subtitle/translation/transcription DTO，以及现有 SRT workflow 作为
风格参考；不会 import 其他功能模块的私有代码或复制其 planner。当时 SR-03/SR-04 只提供已
协调的候选端口，须等负责人独立验收并明确放行，才开始本任务实现。该前置现已满足。

### 1. 入口与工作区

- `SubtitleRenderingCommand` / `SubtitleRenderingOutcome` 严格使用 ADR 第 6 节形状。
  command 只有 asset、SRT manifest 路径、dry_run、overwrite；调用方不能指定输出/样式。
- `SubtitleRenderingCommandHandler.handle(command)` 只校验 command 类型、调用 workflow、
  映射稳定类别到固定人类文案。底层 path/stderr/exception 不拼入公共 error_message。
- `SubtitleRenderingWorkflow.execute(*,asset_id,srt_processing_manifest_path,dry_run=False,
  overwrite=False)` 返回 planned/render、planned/reuse、succeeded/render 或 reused/reuse。
  reuse 不假造 render command，outcome.command 为 null；render 规划返回实际 argv tuple。
- output_root 由 composition 配置，先规范化，再唯一调用 `build_asset_workspace(AssetId,root)`；
  全部输入/正式输出经 `ArtifactType/canonical_filename` 构造。路径校验比较 lexical canonical
  路径，不 resolve 最终 media symlink 后错误拒绝现有 v3 只读链接，也不接受 traversal。

### 2. 抽象端口与已协调适配器

- Store：`exists/read_bytes/size/sha256`，纯规划 staging 路径、不写文件的方法，以及显式创建
  staging、stage_bytes、publish。正式视频只 streaming hash，不读整片到内存。exists 把悬空
  symlink 视为已占位，防止“缺文件即可生成”绕过 conflict。
- Font factory：`ExactFontAdapter(profile.font, texts)`，texts 来自所有权威中英正文；结果具有
  `.identity` / `.measure`。采用已验收的 FontMeasurer/GraphemeSegmenter 协议及 Unicode
  双 identity，glyph 检查不能豁免源正文已有 U+2060 等 code point。
- `Pysubs2AssCodec.library_version` 为实际版本；`encode(render_plan,source_plan)->bytes`；
  `validate(bytes,render_plan,source_plan)->None`，验证严格 canonical ASS 和无损逻辑正文恢复。
- `FfprobeMediaProbe.version()->str`；`probe(path)->RenderMediaDTO`，源/输出都含真实 decode、
  完整 packet CFR 检查，异常由当前执行阶段映射。
- `FfmpegRenderer.tool_identity(pysubs2_version=...,ffprobe_version=...)`；
  `build_command(video_path=...,ass_path=...,fonts_dir=...,output_path=...,profile=...,
  mapping=...)->tuple[str,...]`；`render(command,cwd=...)`。完整编码 argv 必须与事先规划一致，
  底层 -n、全部音频、metadata/chapters 与禁硬件/-shortest 语义不能由 workflow 改写。
- `pixel.preflight(plan,source,staged_ass_path,renderer)` 返回全部 typed PixelResult；逐 cue 真实
  RGBA/frame/log 检查归 SR-03/04，workflow 额外机械验证 cue 顺序/中点/安全/行数/通过标志。
- `validate_rendered_media(source,output,max(original_last_end,ass_last_end))` 为输出纯 QA 端口。
- Clock：`now_utc()` 仅成功 manifest 最后构造时调用，dry-run/reuse/早期失败不得调用。

应用层只依赖本模块 domain、archive_core 公共 DTO 和这些 Protocol/Callable；具体字体、ASS、
ffprobe、renderer、pixel、共享 YAML/process 适配器全部由 composition 显式注入。

### 3. 全上游证据门禁

`load_render_inputs(...) -> ValidatedRenderInputs` 保存 asset/workspace、公共 source plan / SRT
manifest / alignment / translation / report、三项直接 rendering evidence、实际媒体及全部已验证
文件 fingerprint，供发布前只读复核。输入读取是 UTF-8、JSON object、拒绝 duplicate keys 与
NaN/Infinity，不隐式修改或“修复”任何 manifest。

1. SRT manifest 规范路径、asset/status/schema；公共 `SrtProcessingManifestDTO` 严格解析。
2. 其全部五输入和五正文输出逐个验证规范文件名、非空 size/SHA；SRT 本身只作证据，不从其
   恢复正文、语言、断点或 cue。
3. SourceAlignment/TranslationResult/TranslationManifest/SubtitlePlan/SrtReport 公共 DTO 解析；
   `translation.validate_against_alignment`、`source_plan.validate_against_inputs`、
   `srt_manifest.validate_against_plan`；alignment actual SHA 同时匹配 translation manifest/result
   和 SRT plan/manifest，译文 actual SHA 同时匹配 translation manifest 与 SRT plan/manifest。
   report 必须 succeeded、无错误且 summary 与 manifest/cue 数一致。profile/rules/media 完全
   一致，不能只接受 status=succeeded。
4. Transcription manifest `transcription.audio-vad-asr-cache.v1` 的 asset/workflow 成功；当前
   成功 workflow 固定八 records：audio、vad、raw_asr、aligned_asr、transcript_fusion、
   source_alignment、transcription_log、transcription_report。每条记录严格验证结构、canonical
   当前 workspace 路径、status、cache_key/hash/size 与实际文件，不只验证 audio/alignment。
5. 只读取相应 v1 JSON envelope 和溯源字段，不重新执行 ASR/fusion：VAD/raw/aligned 的
   audio_sha256/duration 与 audio 记录一致，raw.vad_cache_key 与 VAD 记录一致，aligned 的
   raw_asr_sha256 与 raw 记录一致；各持久 cache_key 对应自己 record；fusion 的 aligned SHA
   对应 aligned 记录；source_alignment provenance.sentence_input_sha256 对应实际 fusion。
   report asset/status/counts/QA 与 transcription workflow 成功摘要一致；log 亦验证实际证据。
6. workflow.inputs.chapters_sha256 非 null 时，读取当前 canonical chapters.json，验证 actual
   SHA 并用公共 `StructuredTranscriptDTO` 解析；fusion.chapters_sha256、source_alignment 的
   chapter_input_sha256、workflow input 必须一致。null 时不推断或补造章节。
7. workflow.inputs.download_manifest_path 显式指向原下载成功 manifest 时只读验证其公开 JSON
   envelope、同资产、成功状态、canonical video 路径、actual size/SHA 和当前 video 同源；
   v3 现有该路径仍指原 transcription-integration，不自动重定位。其视频和 audio provenance
   video_sha256、SRT manifest/plan 中 actual video SHA 必须完全相同。
8. 源 ffprobe 的宽高/精确微秒/SAR/DAR/FPS/可解码性由 SR-04 验证。旧 SRT
   media.video_duration_ms 来自 **format.duration floor(ms)**，所以与 rendering
   input_media.duration_us//1000 比较，不误与视频流 duration 强行相等；FPS 用有理数比较。
   实际视频流可用时长另外约束全部原/ASS cue，audio duration 与 alignment/provenance 一致。
9. 发布前再次比较上述全部已验证文件 fingerprint，防止长时间编码期间发生输入混代；不重跑
   下载、ASR、provider、SRT planner 或其私有 QA。

负责人确认范围：只强制 manifest **显式证据链** 与公共 DTO 交叉校验。当前 acquisition 没有
逐文件 SHA 成功 manifest，meta.json / transcript.txt / media_ref.json 未被该链逐项 hash 锚定；
不新增 acquisition 业务恢复/人类文本投影推断，不扩大 rendering 三项直接 inputs，也不改写
上游 manifest。SR-07 可用全文件 bytes/mtime 快照证明这些上下文文件未变，但不得称它们已有
hash provenance 验证。这一证据边界须在真实报告如实记录。

负责人已确认 ADR 第 11.3 节英文硬门禁：只用公共 profile 参数与冻结的
`is_layout_whitespace/is_combining_mark`、ZWJ/emoji modifier 排除规则，机械计数并按词 greedy
packing 证明实际 2×42（旧 profile 按自身预算），不 import SP wrapper、不生成 SRT、不重跑
DP。**不使用 raw len，也不把词间空白当计数单位**，避免误拒实际 c4 的94个 code points。
测试保存该真实 c4 文本回归，并覆盖空白/组合标记/ZWJ/modifier/单超长 word 与总容量虽足却
无法按词两行排布的反例。中文 v3 长度/7秒/CPS 全是上游软 warning，绝不套回 v2 硬限制。

### 4. dry-run / reuse / overwrite 状态机

| 当前五份正式输出 | overwrite=false | overwrite=true |
|---|---|---|
| 全无 | 只读构建计划后生成 | 同左 |
| 部分/悬空链接 | artifact_conflict | 显式规划整套替换 |
| 五份齐且所有证据/identity/QA 再验一致 | reused | 显式重新生成 |
| 五份齐但损坏、混代或有效输入/profile/font/tool 变化 | artifact_conflict | 显式重新生成 |

dry-run 使用同一输入/字体/布局/ASS验证与 conflict 逻辑，但不创建目录、不 stage、不发布、不
像素 preflight、不完整编码、不 clock。render command 的 UUID staging 路径可纯计算，不能为
取得 argv 而创建它；工具查询允许已批准的零帧内存启动，区别于完整视频编码。

reuse 重新读取所有正式 bytes/hash、上游完整链、当前 font/glyph/tools、确定性布局重算、ASS
round-trip、现有成功 report 的全部 PixelResult 机械重验和 summary 重算，以及输出 probe/媒体
QA。它不再次运行实际像素 preflight 或完整编码，不 stage、不 publish、不 clock，五份 bytes /
mtime 必须保持不变。成功 PixelResult 的实测数据由原 report hash/成片 hash 锚定，不把只读
机械重验冒称再次做了真实像素采样。

无效上游证据为 input_invalid；现有套件与**有效的新**输入/identity 不匹配才 artifact_conflict。
缺失工具在版本检查阶段为 tool_unavailable；源媒体 probe 错误为 input_invalid，staged 输出
probe/媒体错误为 render_validation_failed。字体/ASS/像素错误保留其稳定类别，未知异常按
当前 stage 的稳定类别映射，不暴露异常原文。

### 5. 同文件系统 staging 与 manifest-last

- Store 纯规划唯一 `.subtitle-rendering.<uuid>` 目录，正式执行显式创建在 workspace 下；
  目录内用规范的安全文件名（尤其 `bilingual.ass`），视频路径尚不存在使 FFmpeg -n 生效。
- stage 使用 exclusive create，不静默覆盖残留；所有失败文件/目录保留，不调用 unlink/rmtree。
  publish 验证同一 filesystem，只原子 rename 一项，不假装多文件事务；无资产锁，与 ADR
  一致，同资产并发直接调用不受支持。
- 内存构造/验证 plan+ASS → stage ASS 并逐字节读回 → 全 cue 真实像素 preflight → stage plan
  并读回 → FFmpeg staged MP4 → 输出 probe/QA → 构造成功 report并 stage/读回 → 全部正文
  evidence 与输入未变复核 → 按 plan/ASS/video/report 发布 → 最后 clock、构造/暂存/读回成功
  manifest → 发布 manifest。
- 上述成功 report 延迟 **已获用户批准并更新 ADR 第 18 节**，不在输出 QA 前谎称
  output_media_passed。发布顺序未变；旧 manifest 若因显式 overwrite 尚留在正式路径，不可能对部分新正文通过
  完整 evidence gate，失败后也不能返回 reused。

### 6. 失败与诊断

- fresh workspace 的受控失败可 best-effort 写规范 failed report；下次运行须显式 overwrite。
  但 dry-run、artifact_conflict 和已有任何正式成功输出时不覆盖它们写 failed report；即使
  overwrite=true，失败也不能拿 failed report 替换已有成功 report。
- 可在本次已创建的 staging 下保留有界失败 report/诊断，记录原始类别和残留路径。接口只
  返回固定错误文案，可返回实际存在的诊断 report 路径供定位；诊断再失败不能掩盖原错误。
  若尚未创建 staging 且有成功套件，不为记录错误破坏复用零写/已有工件安全。
- exception/adapter stderr 最多 2048 字符写本地 finding.diagnostic，公共 error_message 不包含
  命令、路径或 stderr。dry-run/reuse/早期失败不调用 clock；四正文已发布后构造成功 manifest 允许一次 clock。之后 manifest 暂存/读回/发布失败可以留未发布 staged 成功 manifest，但不能形成有效的新成功。编码中断不尝试 checkpoint。

### 7. 预定测试切片

1. inputs：纯 fake store 的整套证据链 fixture，八 transcription record 每项 missing/corrupt /
   path/status/schema/cache-key/跨代，各层 SHA 重签后仍不一致的反例、chapter/download/public
   DTO/覆盖门禁；输入失败前不许 font、pixel、encode 调用。
2. workflow：planned/render、planned/reuse、succeeded/reused、overwrite；真/假工具/字体身份
   变化、部分套件、stage bytes 读回变化、源/输出 probe 对抗、原/ASS末 cue 覆盖。
3. publication：每个 stage/write/readback/publish/clock/manifest 构造位置注入失败；manifest
   永远最后，已有成功输出/上游不被 failed report 覆盖，残留保留。
4. local：同 FS staging、exclusive create、canonical staging 名、video -n 尚不存在、拒异地
   publish/隐式 overwrite；不调用外部工具、不删除临时文件。
5. interface/composition：稳定错误脱敏、配置严格、无 CLI 业务、构造不启动工具/读字体，只有
   execute 才运行只读预检；全 fake 测试后跑完整离线 pytest，再交负责人复验。

## 当前阻断 / 待放行

1. SR-01..04 已 accepted；负责人已明确放行 SR-05 实现，无此前依赖阻断。
2. ADR 第 18 节先 stage 成功 report、后输出媒体 QA 的矛盾现已由用户批准修订解决，不再阻断。
3. 英文冻结计数/词间实际行预算门禁现已由负责人确认，不再阻断；不扩成 SRT planner 或旧
   中文硬预算复活。

以上为编码前设计历史记录；当前已交付下列实现和离线测试，未改写任何 output。

## SR-05 开发交付（2026-10-24，待负责人验收）

### 文件与公共 API

- `src/subtitle_rendering/application/ports.py`：store、font factory、ASS、probe、renderer、clock 的 Protocol；
  `inputs.py`：严格 JSON（含重复字段、NaN/Infinity及指数溢出拒绝）、显式上游链、公共 DTO
  round-trip/交叉覆盖门禁、冻结英文 greedy word-line 预算及发布前 fingerprint 复核。
- `application/workflow.py`：`SubtitleRenderingWorkflow.execute(...)` 与 typed run result；确定性
  内存布局/ASS、当前 identity 先检、整套只读复用、显式覆盖、same-FS staged 内容验证和
  manifest-last。像素记录在编码前独立机械验证；成功 report 只在输出媒体 QA 后构造/暂存。
- `interfaces/workflow.py` 与 `interfaces/__init__.py`：ADR 第 6 节的
  `SubtitleRenderingCommand` / `SubtitleRenderingOutcome` / `SubtitleRenderingCommandHandler`；
  稳定分类映射固定人类文案，不将底层 path/stderr/exception 拼入公共 error_message。
- `infrastructure/local.py`：`LocalRenderingArtifactStore` / `SystemClock`；streaming SHA、悬空
  symlink占位、纯规划unique staging、exclusive staged写入、fsync、同workspace同FS原子rename。
  仅本阶段五种规范正式文件允许发布，不自动清理目录/残留。
- `infrastructure/composition.py`：`build_subtitle_rendering_handler(...)`；严格消费单一配置块，
  显式注入已验收适配器；构造不启动媒体工具、不读取字体。
- 测试新增 `tests/subtitle_rendering/workflow_fakes.py`、`test_inputs.py`、`test_workflow.py`、
  `test_local.py`、`test_composition.py`；不改写其他agent的测试/实现，不触碰任何生成资产。

### 已执行验证

```text
.venv/bin/python -m pytest tests/subtitle_rendering/test_{inputs,workflow,local,composition}.py -q
268 passed in 1.18s

.venv/bin/python -m pytest tests/ -q
2290 passed, 5 skipped in 7.04s

git diff --check
通过（无输出）
```

- 全链 fake 测试覆盖18种必需输入逐项missing/corrupt/empty、八transcription records逐字段
  门禁、重签的跨代cache/provenance、chapter/download原显式路径、公共 DTO/内容覆盖、
  strict JSON、英文单超长word/总容量足但两行不可排、冻结组合符/ZWJ/modifier/空白。
  真实CNBC c4正文94 code points回归证明不是raw len容量。
- workflow覆盖planned/render、planned/reuse、succeeded/reused、dry-run/overwrite、完整/部分/
  损坏套件、identity变化（含合法新profile已无法布局仍先conflict）、零clock/零像素/零编码
  复用、逐stage/readback/publish故障、四正文后clock失败、编码时上游变更、失败诊断与旧
  成功保护。Local测试不执行外部工具；默认composition也有构造惰性证明。
- 对真实v3工作区另做过一次**只读链可行性检查**：使用LocalStore与替身media DTO，163 cues /
  21份显式fingerprints全部通过，没有修改output，也未启动实际字体/libass/FFmpeg。
  这不是源媒体probe或真实集成验收，不能代替SR-07。

### 交接与边界

- SR-05只实现显式证据链与公共契约复核，不重跑上游业务算法、不将acquisition上下文文件
  虚称已有hash锚定；也不从SRT恢复权威正文/分行。
- 输出媒体纯QA由注入的已验收 `validate_rendered_media` 执行；像素的实测保证由已验收SR-03
  adapter执行。复用只机械复验已由report/video fingerprint锚定的旧实测记录，不再次采样。
- 无资产锁/多文件事务；编码中断不checkpoint。四正文发布后manifest步骤故障可能留部分新正文、
  旧manifest或未发布staged成功manifest，下一次必须重新完整证据判定，不能误判reused。
- 只交付离线实现；仍待负责人独立验收、SR-06独立对抗/跨层验收与SR-07完整真实样片。
  未生成或发布正式样片，没有人类播放或出版质量签字。本agent未提交git、未标accepted。

## 负责人验收（2026-10-24 10:36 CST）

已审inputs/workflow/local/composition/handler与测试；首版预审的canonical源名、合法新identity导致无解时的冲突分类已修复。独立测试agent只读预审未发现阻断。负责人独立定向268 passed、完整2290 passed / 5 skipped（7.07s），diff check通过；有限JSON指数与真实c4预算回归均保留。SR-05 accepted，放行SR-06独立测试；尚不代表真实样片/像素与人类播放门槛通过。
