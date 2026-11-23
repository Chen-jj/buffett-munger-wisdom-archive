# subtitle_rendering AGENTS.md

## 最新验收（2026-11-15，验收后doc-only）

NB-12已真实交付623秒/166 cue诊断候选，像素/字形/ASS/媒体技术检查0error，217条warning=上游173＋ASS短gap44；编码1次，新增provider/ASR/对齐0，同/新进程五阶段复用0昂贵调用/0阶段改写。音轨copy且packet SHA-256与源完全相同，是流一致证据，不是核听。
84仅上游逻辑cue容量，显示仍按各语种最多2行/总4行、既有字号和安全框测量；profile SHA-256 `3f046085c35d808ee228ce7bc03840d399dbc2e5b0d78409eebdd99232ae20fc`与NB-09精确相同。负责人实际目视3张原像素tile共18帧，另看frame018原640×360，未见这些帧裁切/缺字/tofu/中英实际重叠；不冒称全面目视、连续播放或核听。
明确布局残余：c162中文双破折号在`chinese_break_offsets=[10]`处拆为上行末一个“—”/下行首一个“—”，原帧可见，归本模块视觉换行，本轮披露不修，不推给源语chunking。c69每天提前4042ms及翻译精度残余属于权威稿内容，技术渲染通过不消除它们；整体语义/出版NOT PASSED，仅供用户诊断复审。
本段仅为全部冻结运行/复用证据完成后的获批doc-only同步，不改生产.py/测试/模型/字号/样式/权威稿，不回签旧manifest身份；下方保留历史实现记录。

2026-11-07 NB-09最终：固定样式完成真实163 cue全量像素、ASS及623秒烧录；词界软择优和数量单位/包装
保护已实片回归，pixel-wrap.v4。仅渲染修复时初译/编辑/SRT均正式复用、provider0调用。根任务NB-09记录
真实播放抽查、39个ASS短间隔及未核听/无人类出版签字，不以零error冒充所有阅读指标通过。

2026-11-06：ADR-0012 权威双语稿接入已实现并完成定向离线验证。保留原排版烧录规则；ASS 两帧不足/未知告警，实际重叠阻断。新版真实 CNBC 已发布623秒/275 cue样片，实际像素/媒体与两种复用通过；核听和语义质量不标通过，范围见 NB-08。

2026-11-07：NB-09 的英文 80 字符是上游逻辑 cue 容量，不是视觉单行限制。现有样式仍按
固定字体和安全区测量，各语种最多两行；不改稿、不移时，超出安全区仍失败。同源冻结的
175-cue 编辑参考在 640×360 以正式样式通过全部布局与实际 libass 逐 cue 像素复验；
这是参考稿的专项核验，不是 NB-09 正式生产成片或声画验收。

## 模块定位

`subtitle_rendering` 负责字幕样式、ASS 生成、烧录计划、ffmpeg 执行，以及渲染工件元数据。

截至 2026-10-24 21:02 CST，SR-01..06公共契约/实现与独立跨层/重签/发布故障验收均已通过并归档。
SR-07 runner已实现，完整离线最近验收2580 passed / 6 skipped；完整623秒/163-cue样片首次编码、
逐cue像素、媒体QA与两次零写复用通过。用户人类播放发现双语语义同步问题，最终验收未通过；
模块整体不标完成。见[复审报告](../../docs/archive/reviews/2026-10-24-rendering-technical-and-semantic-review.md)。
当前探索保留正确的英文时间锚点，调查中文语义块与英文词区间对应；rendering不能私自改上游cue掩盖问题。
用户已接受 [ADR-0006](../../docs/archive/decisions/0006-subtitle-rendering-ass-and-burn-in.md)；此前待决策项
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

## 字幕输入边界（当前）

- 以 `FinalBilingualDraftDTO` / `final_bilingual_draft.json` 为唯一权威字幕内容与时间。
  渲染依赖当前 SRT export manifest 证据并检查三份 SRT 无损投影，不从 SRT 恢复稿件。
- 核验最终稿源词覆盖、初译来源、全部当前阶段 manifest 和媒体证据；拒绝损坏文件、
  来源指纹错配及混合代次。容量、CPS、非重叠短间隔是警告，不重切、改译或挪时。
- 转录报告的声学词数、插值词数和插值比例以已验指纹的融合前 forced alignment 工件核对；
  融合后的 canonical 词数可能因多对一等变换而不同，仍由最终稿独立验证完整覆盖。
- 保留实际字体/face/glyph、安全像素框、媒体流/映射/音频复制和 manifest-last。
  百分秒 half-up 仅用于 ASS 投影；使用实际 decoded PTS 复验投影后的两帧间隔，
  不足/未知警告定位到左 cue 的原始起止，投影 gap/帧数单独写诊断，不二次移时；
  越界、重叠或非正时长阻断。
- `pixel-wrap.v4` 延续原有豁免：仅豁免权威中文首码点 U+2026 的首视觉行；不豁免视觉换行造成的行首
  省略号、英文、ASCII `...`、其他闭合标点、字体或安全框。公共计划复验同一省略号规则。

## 分层规则

- `domain/`：渲染 profile、字幕样式、渲染输入集、渲染计划、渲染工件等概念。
- `application/`：build-ass、render-video、verify-render-inputs、generate-render-manifest 用例。
- `infrastructure/`：`pysubs2` ASS 适配器、ffmpeg 进程执行器、字体发现、文件系统输出。
- `interfaces/`：CLI 处理器、渲染进度消息、面向评审/orchestration 的摘要。

## 真实集成与样片交付

- 当前入口统一归 orchestration：NB-08 从空工作区生成权威稿、ASS 和真实成片，
  local_media 场景复验当前同源文件的渲染/复用；无旧 SR-07/v3 runner 兼容入口。
- 逐 cue 实际 libass 像素及成片媒体安全校验不变。正式复用零像素渲染、零视频编码、
  零写；静态 verify 只核验已记录媒体契约、来源链和 ASS，不假装执行新工具探测。
- 历史 623 秒/163-cue 技术样片和用户语义未验收是归档事实，不代表新版质量状态。

## 技术方向

- 以ADR-0006的五份规范输出、dry-run、整套证据复用、逐cue像素预检和manifest-last语义为准；
  未实现前不得自创旧SRT直烧或“视频存在即完成”的入口。
- ASS/样式生成与 ffmpeg 执行分离，各自可独立测试。
- 烧录渲染通过适配器使用 `ffmpeg`/libass。
- CRF、preset、分辨率、字幕样式等质量设置作为显式 profile 管理。
- 优先支持 dry-run 命令规划，便于调试与评审。


## NB-09 中文视觉断行（2026-11-07）

- `pixel-wrap.v4` 保留 v3 在标点择优之后、像素宽度平衡之前软性优先中文词边界的规则，避免可用词边界下拆成「价／值」等。保留完整 grapheme 候选，词边界不是硬保护；只有词内切分能安全容纳时仍可用，不改权威正文、cue 或时间，不缩字。
- 数字紧密单位规则 `numeric-units.v2` 增补「盎司」「份」，避免 `8盎司`、`8000万份` 被视觉断开；已匹配数量单位后紧接的包装后缀「装」也在同一跨度内（如 `500毫升装`、`8盎司装`），不吞并后面的「的」，不把未匹配单位的「装」独立认作单位。布局版本随之改为 v4，旧 v3 缓存不能复用。字典软择优不能绕过既有数字单位硬保护。
- 既有 segmentation 端口增加 `lexical_boundaries`；domain 只消费边界。基础设施固定 `jieba==0.42.1`、HMM=False 和包内词典 SHA-256 `7197c3211ddd98962b036cdf40324d1ea2bfaa12bd028e68faa70111a88e12a8`，直接由已核字节构造分词表，不读取用户词典或 jieba 磁盘缓存。依赖与词典身份绑定 measurement identity；版本、字节不符失败，不 fallback。
- 实际新样片仍须逐 cue 字体/ASS/像素与媒体复验，本项断行测试不代表翻译或核听通过。
