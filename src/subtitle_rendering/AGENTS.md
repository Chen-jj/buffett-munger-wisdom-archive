# subtitle_rendering AGENTS.md

## 模块定位

`subtitle_rendering` 负责字幕样式、ASS 生成、烧录计划、ffmpeg 执行，以及渲染工件元数据。

ADR-0003 的上游字幕实现已通过离线跨层及 CNBC 真实技术集成，负责人/agent文本审读也已执行；
这不是人类签字、语义对齐或出版级字幕质量通过。人物/地名错位、“风/险”“认/为”、破折号与
专名拆分等上游已知限制见 [SP-08](../../docs/tasks/SP-08-real-sample-and-final-status.md)，
不能因上游硬门禁通过而视为本模块视觉或成片质量已经验收。

## 职责

- 把校验通过的公共字幕 plan 转换为带样式的 ASS 或可渲染资产。
- 规划硬字幕输出的 ffmpeg 命令，不隐藏影响用户观感的质量参数。
- 采集渲染设置、输入哈希、输出路径与评审 sidecar。
- 视觉样式决策与 SRT 文本处理保持分离。

## 字幕输入边界（ADR-0003，待本模块实现）

- 以 `archive_core.interfaces.SubtitlePlanDTO` / `subtitle_plan.json` 为唯一权威字幕内容，
  不从 English/Chinese/Bilingual SRT 反推词范围、语言身份或 cue 切分。
- 消费前验证 `srt_processing_manifest.json` 的整套输入/输出证据与 plan 身份，不能只看
  `status=succeeded` 或文件存在；拒绝部分输出、损坏文件与混合代次。
- 按 `english_text` / `chinese_text` 取逻辑正文；视觉换行、字体/字号、像素 QA、ASS 与烧录
  属于本模块。SP-11 候选 SRT 的确定性英文两行只是计数行预算投影，plan 不存视觉 lines；
  不得从 SRT 行数反推权威内容，或为排版静默改变 cue 时间、正文、字符范围或 speaker 标签。
- 三份 SRT 共用 cue/时间；双语中文在上、英文在下。旧 profile v1 为英文42/中文加权16；
  SP-10..11 用户试验授权的候选 v2 为英文最多两行、每行42，中文一行16且中文内英文按词计数。
  本模块不能扩大实际消费的 profile 预算，也不能把计数行预算当像素适配、把比例对应或
  word gap 当语义/静音证明。候选取舍待用户审阅，并非已接受的出版策略。
- SP-13/14候选v3将中文16与显示7秒改为软告警目标，不另设硬时长上限；中文仍一逻辑行，
  英文实际2×42仍硬限制，codec投影身份不变。rendering不得误把旧v2硬中文预算套回v3，
  也不得将软目标理解为任意长文本已经像素适配。仍须独立验证字体/像素/成片，不能静默
  截断源讲话、改译、改cue时间或重排正文以消除上游告警。
- SP-14公共契约、三SRT回读、超目标告警与零写复用的候选技术门槛已通过，合并树完整
  离线为1395 passed / 5 deselected；SP-15真实隔离163-cue样本与全97句比较交付也已技术验收。
  S17/S22等语义/节奏残余使其不宜质量定版；此技术验证不实现本模块，
  也不构成字幕语义、像素适配或出版级质量通过。

## 分层规则

- `domain/`：渲染 profile、字幕样式、渲染输入集、渲染计划、渲染工件等概念。
- `application/`：build-ass、render-video、verify-render-inputs、generate-render-manifest 用例。
- `infrastructure/`：`pysubs2` ASS 适配器、ffmpeg 进程执行器、字体发现、文件系统输出。
- `interfaces/`：CLI 处理器、渲染进度消息、面向评审/orchestration 的摘要。

## 技术方向

- ASS/样式生成与 ffmpeg 执行分离，各自可独立测试。
- 烧录渲染通过适配器使用 `ffmpeg`/libass。
- CRF、preset、分辨率、字幕样式等质量设置作为显式 profile 管理。
- 优先支持 dry-run 命令规划，便于调试与评审。
