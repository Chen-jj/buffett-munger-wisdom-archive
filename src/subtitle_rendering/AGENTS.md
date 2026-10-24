# subtitle_rendering AGENTS.md

## 模块定位

`subtitle_rendering` 负责字幕样式、ASS 生成、烧录计划、ffmpeg 执行，以及渲染工件元数据。

截至 2026-10-24 21:02 CST，SR-01..06公共契约/实现与独立跨层/重签/发布故障验收均已通过并归档。
SR-07 runner已实现，完整离线最近验收2580 passed / 6 skipped；完整623秒/163-cue样片首次编码、
逐cue像素、媒体QA与两次零写复用通过。用户人类播放发现双语语义同步问题，最终验收未通过；
模块整体不标完成。见[复审报告](../../docs/reviews/2026-10-24-rendering-technical-and-semantic-review.md)。
当前探索保留正确的英文时间锚点，调查中文语义块与英文词区间对应；rendering不能私自改上游cue掩盖问题。
用户已接受 [ADR-0006](../../docs/decisions/0006-subtitle-rendering-ass-and-burn-in.md)；此前待决策项
均采用推荐方案：v1只发布双语硬字幕成片，中文/英文各最多两条视觉行、总计最多四行，固定
字号下超出安全区域受控失败；使用精确Hiragino字体文件/face/hash且禁止fallback；libx264
CRF18 medium/yuv420p，复制全部音频，不使用硬件编码。ADR接受不代表实现完成。
ADR-0003 的上游字幕实现已通过离线跨层及 CNBC 真实技术集成，负责人/agent文本审读也已执行；
这不是人类签字、语义对齐或出版级字幕质量通过。人物/地名错位、“风/险”“认/为”、破折号与
专名拆分等上游已知限制见 [SP-08](../../docs/archive/tasks/SP-08-real-sample-and-final-status.md)，
不能因上游硬门禁通过而视为本模块视觉或成片质量已经验收。

## 职责

- 把校验通过的公共字幕 plan 转换为带样式的 ASS 或可渲染资产。
- 规划硬字幕输出的 ffmpeg 命令，不隐藏影响用户观感的质量参数。
- 采集渲染设置、输入哈希、输出路径与评审 sidecar。
- 视觉样式决策与 SRT 文本处理保持分离。

## SR-02 纯 domain 开发交付（待负责人验收）

- `domain.models` 定义 `FontMeasurer.measure(text,font_size,outline_width,shadow)` 和
  `GraphemeSegmenter.boundaries(text)` 注入端口；domain 不 import 字体/ASS/regex 等外部库。
  完整 Unicode grapheme 由 adapter 的 `regex==2026.7.19` / `\X` 提供，版本必须绑定到字体
  measurement identity；不把上游不完整 character boundary 规则冒称完整 grapheme。
- stdlib `unicodedata` / decimal 分类还受 Python 的 Unicode DB 影响，因此额外绑定
  `unicode-classification-<unicodedata.unidata_version>`；两个身份作为分号分隔的完整 token
  验证，缺失/运行时版本变化/伪造子串均拒用，不能声称 profile v1 已冻结运行库分类数据。
- `pixel-wrap.v1` 冻结 `numeric-units.v1` 表与边界评分：保护 Latin 词/内部撇号连字符、
  Unicode decimal 数字分隔符、货币、百分比、科学计数、紧密 SI/已列中文单位；不推断任意
  汉字为单位。中文只在完整 grapheme 边界、英文只在现有词间空白分行，原始切片保留空白。
- 所有一/两行路径按 ADR 字典序选择，无断点 penalty=0，强/弱/普通边界 penalty=0/1/2；
  不擅自添加最少行数偏好。中英独立胜出后合并验总高度，固定字号无解即 `layout_failed`。
- half-up 缩放、安全区域、公共 plan 构建和只读重算验证均已实现；`config.yaml` 三个未消费
  的旧样式块已替换为单一 `subtitle_rendering`，没有兼容 shim。
- 自有 domain 测试 181 passed，当时完整离线为 1773 passed / 5 skipped。默认测试不读系统
  字体、不执行 FFmpeg；这些验证不代表真实字体、像素或完整样片验收。

## 字幕输入边界（ADR-0003/0006，已实现）

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

## 真实集成与样片交付（ADR-0006第20.2节，技术通过、最终验收未通过）

- 使用同一CNBC资产的transcription持久集成产物、SP-08A真实translation验收产物及SRT v3
  集成产物；不能混入translation独立live测试的synthetic fixture或手写/合成替代品。
- 默认复用既有上游，不自动跑下载、ASR、provider或SRT planner；显式运行缺产物时返回
  非零precondition_missing并列出路径，不静默skip。
- 实际生产handler必须输出并持久保留完整623秒/163-cue双语样片`video_中文字幕.mp4`和
  其余四份规范工件；不得只留在pytest临时目录，必须交付绝对路径、hash、时长和来源证据。
- 首次succeeded后同进程/独立进程reused均零写、零视频编码，上游原文件及链接目标不变。
- 样片已持久交付到v3 workspace的`video_中文字幕.mp4`；技术证据在
  `output/subtitle-rendering-integration/SR07-20261024-first-v1/`。用户已播放并反馈语义问题，
  不把静态抽帧、技术通过或人类“已播放”本身当作接受样片/出版质量签字。

## 技术方向

- 以ADR-0006的五份规范输出、dry-run、整套证据复用、逐cue像素预检和manifest-last语义为准；
  未实现前不得自创旧SRT直烧或“视频存在即完成”的入口。
- ASS/样式生成与 ffmpeg 执行分离，各自可独立测试。
- 烧录渲染通过适配器使用 `ffmpeg`/libass。
- CRF、preset、分辨率、字幕样式等质量设置作为显式 profile 管理。
- 优先支持 dry-run 命令规划，便于调试与评审。
