# ADR-0006：subtitle_rendering 的确定性 ASS 排版与硬字幕烧录契约

- 状态：已接受；技术实现与真实样片已交付，SR-07最终验收未通过（2026-10-24）
- 日期：2026-10-23
- 集成测试补充确认：2026-10-23，复用 transcription/translation/srt_processing 真实集成产物并持久输出样片。
- ASS时间补充确认：2026-10-23，权威毫秒保持；ASS投影最近10ms、5ms向上，显式记录投影和差值。
- 实现可行性补充确认：2026-10-23 23:54 CST，允许预检前暂存ASS；批准可逆U+2060反斜线显示控制。
- 影响模块：`archive_core`、`subtitle_rendering`、`infrastructure`、`orchestration`、`cli`
- 关联决策：ADR-0003（本 ADR 消费其公共字幕 plan，不取代其 cue 决策）
- 所属阶段：Phase 1

## 1. 决策摘要

`subtitle_rendering` 是 `srt_processing` 的直接下游。它以公共
`SubtitlePlanDTO` / `subtitle_plan.json` 为唯一权威字幕内容，从逻辑中英文正文生成确定性视觉
换行和双语 ASS，通过 FFmpeg/libass 烧录一份双语硬字幕 MP4，并以 manifest 驱动复用和
manifest-last 发布。

```text
srt_processing_manifest.json
subtitle_plan.json + video.mp4
             |
             v
 [整套上游证据与公共 DTO 门禁]
             |
             v
 [字体解析 + 像素测量 + 确定性视觉换行]
             |
             v
 subtitle_rendering_plan.json
             |
             v
 [ASS 生成、读回、逐 cue 像素预检]
             |
             v
 bilingual.ass
             |
             v
 [FFmpeg/libass -> 临时 MP4 -> ffprobe 验证]
             |
             v
 video_中文字幕.mp4
 subtitle_rendering_report.json
 subtitle_rendering_manifest.json（最后发布）
```

核心决策：

- v1 只发布双语硬字幕成片；中文在上、英文在下，不同时实现中文或英文单语烧录变体。
- 不从 English/Chinese/Bilingual SRT 恢复内容、语言或 cue；SRT 只作为上游证据集的一部分验证。
- 视觉分行可以改变同一 cue 内的显示行，但不得修改 cue 时间、逻辑正文、字符范围、词范围、
  section 或 speaker 溯源。
- ASS时间格式仅有百分秒精度：权威cue与render plan保留原毫秒，ASS投影使用第12.1节明确量化策略，不冒称毫秒完全相同。
- 中文最多两条视觉行，英文最多两条视觉行，总计最多四行。英文只能在词间空白断行；中文
  只能在 Unicode grapheme 边界断行，并避免不自然的行首/行尾标点。
- 字体大小固定于 profile，不按单 cue 静默缩字。选定样式下无法进入安全区域时受控失败，
  不截字、不改译文、不改 cue 时间、不允许 libass 自行增加行数。
- v1 使用精确的 macOS `Hiragino Sans GB.ttc` 文件、TTC face 与 SHA-256；禁止字体 fallback。
- v1 使用软件 `libx264`、CRF 18、preset `medium`、`yuv420p`；复制全部音频流，不静默转码。
- ASS/布局计划应确定性；成片字节只承诺在相同输入、字体与完整工具链身份下可审计和复用，
  不宣称跨 FFmpeg/libass/libx264 版本字节一致。
- dry-run 做输入、字体、布局与命令规划，但零写入且不执行视频编码。
- 成功 manifest 是整套渲染完成的唯一证明；不得以视频文件存在或 FFmpeg 退出 0 代替验证。
- v1 没有编码 checkpoint 或并发锁。中断后重新编码整个视频；未来由 orchestration 保证同一
  资产串行调用。

## 2. 背景与顺序选择

仓库当前已经实现 acquisition、media download、transcription、translation 和
`srt_processing`。ADR-0003 发布统一的 `subtitle_plan.json`，其中每个 cue 已有稳定 ID、毫秒
时间、逻辑中英文正文、来源 fragment 和时间调整方法。SRT 是该 plan 的投影，不是新的权威
内容来源。

当前 `subtitle_rendering` 仍是脚手架。先实现 CLI、Web UI 或 orchestration 会迫使薄接口围绕
尚未冻结的渲染输入、输出、失败和复用语义工作，之后还需返工。因此阶段顺序固定为：

```text
subtitle_rendering -> orchestration -> CLI -> Web UI / 人工评审体验
```

本 ADR 只冻结 rendering 契约和实现方向，不把模块状态标记为已实现。

## 3. 术语

| 术语 | 本 ADR 中的含义 |
|---|---|
| 逻辑正文 | plan 中的 `chinese_text` / `english_text`；不包含视觉换行或 ASS 标签。 |
| 视觉行 | 同一 cue 为适配字体和画面宽度而形成的显示行，不改变 cue 内容或时间。 |
| ASS | 可表达字体、颜色、位置和强制换行的字幕格式；本模块将其作为 libass 输入。 |
| PlayRes | ASS 的设计坐标系；v1 使用实际视频像素宽高。 |
| 安全区域 | 允许字幕像素出现的画面矩形；描边和阴影也必须位于其中。 |
| 字体 face | TTC 字体集合中的具体字体成员；只记录文件名不足以唯一识别。 |
| fallback | 目标字体缺字时渲染器改用另一字体；v1 禁止静默 fallback。 |
| dry-run | 完成只读门禁、布局和命令规划，但不写工件、不执行视频编码。 |
| staged output | 与正式输出位于同一文件系统、尚未发布的临时文件。 |
| manifest-last | 先验证并发布正文工件，最后发布成功 manifest。 |
| 像素预检 | 在透明画布上由实际 libass 渲染每个 cue，检查非空和边界框。 |
| 技术验收 | 证明契约、像素边界、媒体输出和复用成立，不等于翻译或出版质量签字。 |

## 4. 模块边界

### 4.1 负责

- 验证 SRT processing manifest、其全部输入/输出证据、公共 plan 身份与规范视频。
- 解析精确字体文件，验证文件 hash、TTC face、family 和正文 glyph 覆盖。
- 根据实际视频尺寸、固定 profile 和字体测量结果生成确定性视觉换行。
- 生成、读回并验证双语 ASS。
- 规划 dry-run 和正式 FFmpeg 命令，通过共享进程适配器执行。
- 重新探测临时成片，验证视频、音频、时长、流映射和容器属性。
- 输出 plan、ASS、成片、report 和成功 manifest；完整校验后复用。

### 4.2 不负责

- ASR、翻译、字幕 cue 规划或修复上游词时间。
- 改写、压缩、截断、重排或补充中英文正文。
- 为排版延长、缩短或移动 cue。
- 从 SRT 行数、画面 OCR、speaker 或 section 标题推断权威正文。
- 生成软字幕轨或同时发布中/英单语烧录成片。
- 用硬件编码替换规范软件编码。
- 镜头检测、台标检测、自动内容编辑或出版签字。
- CLI 参数解析、Web UI 或全管线依赖调度。

## 5. 分层架构

```text
src/subtitle_rendering/
├── domain/
│   ├── models.py          # profile、视觉事件、render plan、finding
│   ├── layout.py          # 纯断行搜索与安全区域规则
│   └── validation.py      # 纯计划/布局 QA
├── application/
│   ├── ports.py           # store/font/ASS/probe/renderer/clock 端口
│   ├── inputs.py          # 上游证据与公共 DTO 门禁
│   └── workflow.py        # 复用、生成、渲染、验证、发布
├── infrastructure/
│   ├── composition.py     # 显式生产组装
│   ├── local.py           # 文件、SHA-256、同文件系统暂存、原子发布
│   ├── fonts.py           # 字体 identity、glyph 覆盖、像素测量
│   ├── ass.py             # pysubs2 ASS adapter
│   ├── probe.py           # ffprobe adapter
│   └── ffmpeg.py          # 命令生成与执行
└── interfaces/
    └── workflow.py        # command/outcome/handler
```

- `domain/` 不依赖 Pillow、pysubs2、FFmpeg、subprocess 或文件系统。
- `application/` 只依赖 domain、`archive_core` 公共契约及抽象端口。
- Pillow/pysubs2/FFmpeg/字体文件只出现在 infrastructure adapter。
- `interfaces/` 不持有布局、媒体或复用规则。
- 共享 subprocess 能力从 `infrastructure.infrastructure.process` 使用；不得另写 shell runner。

## 6. 对外 command 与 outcome

### 6.1 Command

```python
@dataclass(frozen=True)
class SubtitleRenderingCommand:
    asset_id: str
    srt_processing_manifest_path: str
    dry_run: bool = False
    overwrite: bool = False
```

调用方不提供输出路径、字体 family、样式或编码参数；这些由规范 workspace 和版本化 rendering
profile 决定。`asset_id` 使用 `source:group:item`，workspace 必须由
`archive_core.application.build_asset_workspace()` 构造。

### 6.2 Outcome

```python
@dataclass(frozen=True)
class SubtitleRenderingOutcome:
    status: str                 # planned / succeeded / reused / failed
    action: str | None          # render / reuse
    plan_path: str | None
    ass_path: str | None
    video_path: str | None
    report_path: str | None
    manifest_path: str | None
    cue_count: int
    warning_count: int
    command: tuple[str, ...] | None
    error_category: str | None
    error_message: str | None
```

dry-run 与正式执行使用同一输入和布局逻辑：

- 没有现有工件：返回 `planned/render` 与具体 argv，不写文件、不编码。
- 完整结果可复用：返回 `planned/reuse`，不为了展示命令伪造一次渲染。
- 部分、损坏或身份冲突：与正式执行一样返回 `artifact_conflict`。
- `dry_run=True` 与 `overwrite=True` 可以组合，用于查看显式覆盖计划，但仍零写入。

## 7. 正式输入和门禁

rendering 的外部入口只接收 `srt_processing_manifest.json`，但消费前必须验证整条证据链：

1. `asset_id`、manifest 规范路径、schema 和 `status=succeeded`；
2. manifest 中 transcription manifest、source alignment、translation manifest、translation
   result、video 的规范路径、大小和 SHA-256；
3. manifest 中 subtitle plan、三份 SRT 和成功 report 的规范路径、大小和 SHA-256；
4. 使用公共 `SrtProcessingManifestDTO`、`SubtitlePlanDTO`、`SourceAlignmentDTO` 和
   `TranslationResultDTO` 解析相关 JSON；
5. manifest 与 plan 的 profile、media、规则和全部直接指纹一致；
6. `plan.validate_against_inputs()` 重新证明词、句、译文字符、section、speaker 和时间锚点覆盖；
7. 实际 `video.mp4` 的 SHA-256 同时匹配 manifest 与 plan；
8. ffprobe 证明存在可解码主视频流，并取得宽高、SAR/DAR、帧率、时长、像素格式及音频流描述。

rendering 不 import `srt_processing` 私有 planner、规则或 QA，不重新运行其 DP，也不从 SRT
恢复 plan。三份 SRT 只做证据完整性验证；实际 ASS 正文始终来自 plan。

## 8. 公共输出契约

在 `archive_core.domain.ArtifactType` 增加独立类型，不能复用含义不明确的通用 `MANIFEST`：

| 工件类型 | 规范文件名 | schema / 角色 |
|---|---|---|
| `SUBTITLE_RENDER_PLAN` | `subtitle_rendering_plan.json` | `subtitle-rendering.plan.v1` |
| `BILINGUAL_ASS` | `bilingual.ass` | 确定性 libass 输入 |
| `RENDERED_VIDEO` | `video_中文字幕.mp4` | 现有规范成片文件名 |
| `SUBTITLE_RENDER_REPORT` | `subtitle_rendering_report.json` | `subtitle-rendering.report.v1` |
| `SUBTITLE_RENDER_MANIFEST` | `subtitle_rendering_manifest.json` | `subtitle-rendering.manifest.v1` |

### 8.1 Render plan

公共 render plan 至少保存：

- asset ID、SRT processing manifest / subtitle plan / video 指纹；
- 输入视频宽高、SAR/DAR、帧率、时长和流摘要；
- rendering profile 完整参数、版本和内容 SHA-256；
- 字体文件 SHA-256、字节数、family、style、TTC face/index；
- ASS PlayRes、安全区域和样式；
- 每个 `c1..cN` 的原时间、逻辑正文 SHA-256、中文/英文视觉断点 offset、行数、测量宽高和
  预计边界框；
- 每cue的ASS投影起止时间及相对权威毫秒的有符号差值，绑定`nearest-centisecond-half-up.v1`身份；
- FFmpeg 编码与流映射的语义参数。

视觉断点使用逻辑正文中的 Unicode code point 间 offset，不仅保存已经断开的字符串。读取 plan
时必须从权威正文和 offset 重建视觉行，并证明移除视觉分隔后没有增删、替换或重排正文。

执行时间、临时文件路径和 FFmpeg stdout/stderr 不进入 plan，因此相同输入和工具 identity 下
plan 与 ASS 可以字节稳定。

### 8.2 Report

report 保存：

- `succeeded` 或 `failed`；
- finding code、severity、cue ID、时间、观测宽高和边界框；
- cue 数、中文/英文各行数分布、最大宽高、四行 cue 数；
- font/glyph、ASS round-trip、像素预检及输出媒体 QA 摘要；
- 失败类别和受控诊断。

上游 `reading.chinese_length`、`timing.target_duration`、CPS 等 warning 可以作为上下文计数引用，
但 rendering 不把它们升级为自身硬错误。rendering 的硬错误是实际字体/安全区域/媒体契约不符。

### 8.3 Manifest

成功 manifest 至少保存：

- asset、`status=succeeded`、UTC 完成时间；
- SRT processing manifest、subtitle plan、video 的直接证据；
- rendering profile 与字体 identity；
- pysubs2、FFmpeg、ffprobe、libass、libx264 的实际版本；
- 输入和输出媒体探测结果；
- plan、ASS、成片、成功 report 的规范路径、大小、SHA-256；
- 与 report 一致的摘要。

manifest 不声称内容语义、翻译质量或出版签字通过。

## 9. Rendering profile v1

现有未使用的 `subtitle_style`、`bilingual`、`ffmpeg` 配置在实现时合并为一个显式
`subtitle_rendering` 配置块；仓库仍在迁移中，不为旧脚手架配置提供兼容 shim。

```yaml
subtitle_rendering:
  profile: "bilingual-burnin.hiragino-640x360.v1"
  output_mode: "bilingual"
  reference_width: 640
  reference_height: 360
  horizontal_margin: 32
  vertical_margin: 42
  maximum_subtitle_height: 160
  maximum_chinese_lines: 2
  maximum_english_lines: 2
  maximum_total_lines: 4
  alignment: 2
  font:
    path: "/System/Library/Fonts/Hiragino Sans GB.ttc"
    sha256: "f887295caf2881cab9554b14c5ab4c9ee624c3895599da152ec37416b5aefae0"
    family: "Hiragino Sans GB"
    style: "W3"
    face_index: 0
  chinese:
    font_size: 30
    primary_color: "&H00FFFFFF"
  english:
    font_size: 20
    primary_color: "&H0060E6FF"
  outline_color: "&H00000000"
  outline_width: 2
  shadow: 1
  encoder:
    video_codec: "libx264"
    crf: 18
    preset: "medium"
    pixel_format: "yuv420p"
    audio_mode: "copy-all"
    movflags: "+faststart"
```

2026-10-23 已用 `fc-query` / `fc-scan` 核对该 TTC：index 0 为 `Hiragino Sans GB`、style
`W3/Regular`，index 1为界面字体，index 2/3为W6。生产字体 adapter 仍必须独立读取并核对这些
事实，不能只因配置写了0就接受，也不得选择其他字体 face 兜底。

当前字体是 macOS 系统专有字体，不复制、不提交到仓库。缺文件、hash 变化、face 不存在或正文
缺 glyph 时失败。未来跨平台迁移需另立决策，选择许可证允许的固定开源 CJK 字体并升级 profile。

## 10. 分辨率缩放和安全区域

profile 中的尺寸以 640×360 为参考。实际像素值使用非负整数的 round-half-up 缩放：

```text
horizontal_value(W) = round_half_up(base * W / 640)
vertical_value(H)   = round_half_up(base * H / 360)
font_size(H)        = round_half_up(base * H / 360)
```

ASS `PlayResX/PlayResY` 使用实际视频宽高。安全区域为：

```text
left   = scaled horizontal_margin
right  = W - scaled horizontal_margin
bottom = H - scaled vertical_margin
top    = bottom - scaled maximum_subtitle_height
```

文字、描边和阴影的实际 libass alpha 边界框都必须位于该矩形。v1 保留输入分辨率、宽高比和
帧率，不增加 resize、crop、pad 或旋转策略。带旋转 metadata、非正方形像素或显示宽高与编码
宽高不一致时，若 adapter 不能明确得到最终显示坐标，受控失败而不是猜测。

## 11. 确定性视觉换行

### 11.1 通用不变量

- 每个 cue 的 `start_ms` / `end_ms` 与 `SubtitlePlanDTO` 完全相同。
- 换行只插入显示分隔，不删除空白以外的字符，不改变正文顺序。
- 不对单 cue 缩小字体，不压缩字符间距，不截断，不用省略号替换。
- 行宽测量包含实际字体、字号、描边和阴影的安全余量。
- 候选枚举顺序变化不能改变最终结果；完整断点 offset 是最后 tie-break。

### 11.2 中文

中文逻辑正文允许最多两条视觉行。候选断点只能位于 Unicode grapheme 边界，且不得拆分：

- combining character sequence；
- emoji ZWJ/variation sequence；
- 连续 Latin word、内部撇号或连字符；
- 数字内部的点、逗号、冒号及紧密数字单位。

候选优先级依次为：句末/强停顿标点后、逗号/顿号等弱停顿后、普通合法 grapheme 边界。
禁止闭合标点单独位于行首，禁止开放标点单独位于行尾。普通 grapheme 边界只影响视觉排版，
不能被描述成新的语义 cue 切分。

ADR-0003 v3 的16单位、7秒和9CPS均是上游软目标；超过它们不构成 rendering 失败。只有两条
中文视觉行仍无法在实际安全宽度内完整放下时，才是 `layout_failed`。

### 11.3 英文

英文逻辑正文最多两条视觉行，只能在现有空白的词边界断行。不得拆词、插入连字符或依赖
SRT 投影中的既有换行。上游实际2×42仍是 plan 合法性的硬门禁，但 rendering 重新使用字体
像素测量，不能把42字符当作像素适配证明。

### 11.4 路径选择

对一行和两行的全部合法路径，按下列字典序选择：

1. 超出安全宽度的行数；该项必须为0，否则路径非法；
2. 非优选标点边界数；
3. 行首/行尾标点问题数；该项必须为0，否则路径非法；
4. 各行像素宽度最大值；
5. 各行宽度差的平方和；
6. 完整断点 offset。

中文、英文各自得到1～2行后组合，实际总高度必须不超过安全区域和四行上限。无合法路径则
失败，不让 libass 再做隐式自动换行。

## 12. ASS 生成与回读

v1 每个 cue 生成一个底部居中的 ASS event，中文视觉行在前，英文视觉行在后。使用一个基础
样式保持定位、描边、阴影和 margin 一致，通过受控 inline override 只切换英文的字号和颜色。

```text
<中文第1行>\N<中文第2行>\N
{受控英文样式}<英文第1行>\N<英文第2行>
```

实际 event 不为缺少的行生成空白行。ASS 固定：

- `PlayResX/PlayResY` 为实际视频尺寸；
- `ScaledBorderAndShadow=yes`；
- `Alignment=2`；
- 禁止自动换行，只接受模块显式产生的 `\N`；
- 不显示 speaker、section title 或 cue ID；cue ID 可进入不显示的 actor/name 元数据；
- UTF-8、无 BOM、LF、文件末尾换行；
- 字幕正文中的反斜线、大括号、`\N`、HTML/ASS 类似文本必须按纯文本转义，不能成为 override。

纯文本编码使用版本化`bilingual-ass.word-joiner.v1`：每个源反斜线后插入U+2060 WORD JOINER，
阻止其与后续N/n/h/大括号组成libass控制；源大括号按libass支持的方式转义。写出/回读由严格
inverse scanner证明原文与视觉断点完全一致，不使用pysubs2的plaintext丢弃显示控制来冒充保真。
只有模块插入的U+2060属于零像素显示控制并免glyph检查；源正文（包括源U+2060）仍完整接受
glyph门禁。实际libass对抗像素测试必须证明源字符可见语义、零宽控制不增加像素/换行且无fallback。

ASS adapter 写出后必须重新读回并逐条比较：

- event 数量和 `c1..cN` 顺序；
- 起止时间与第12.1节的ASS投影毫秒一致，原始毫秒另由render plan对权威plan精确校验；
- 受控样式身份；
- 视觉断点；
- 去除模块插入的显示控制后可恢复 plan 中完全相同的逻辑正文。

### 12.1 ASS百分秒时间投影（2026-10-23用户批准）

ASS与锁定的pysubs2 1.8.1使用`H:MM:SS.cc`，不能无损写出任意毫秒。当前真实163 cues均有
非10ms对齐边界，原“ASS回读起止毫秒完全不变”的要求不可执行，按本节替代：

- `SubtitlePlanDTO`及render plan的权威`start_ms/end_ms`完全不变，不重切或移动上游cue。
- 仅ASS显示投影：`ass_ms = ((source_ms + 5) // 10) * 10`；最近10ms，恰好5ms时向上。
- render plan逐cue记录原时间、`ass_start_ms/ass_end_ms`、起止有符号差值及策略身份；每边绝对误差≤5ms。
- ASS回读必须精确匹配投影时间，并再次证明原时间与公共权威plan相同；不能将投影时间写回上游。
- 投影后必须保持正时长、顺序、无重叠且不超媒体可用时长；不合法时受控失败，不再做二次修正。
- 像素预检采样使用ASS投影区间内的中点；成片QA同时检查原/投影末cue覆盖。

依据：仓库本地pysubs2 1.8.1的`SubstationFormat.ms_to_timestamp()`明确按10ms half-up写出。

## 13. 字体与 glyph 门禁

字体 adapter 负责：

1. 读取配置中的精确文件，不通过 family 名称搜索替代文件；
2. 验证大小与 SHA-256；
3. 选择精确 TTC face，验证 family/style；
4. 验证全部中英文正文 code point 有 glyph；
5. 以该 face 和缩放后字号提供确定性测量；
6. 将文件 hash、face 和测量 adapter 版本作为复用 identity。

不允许系统字体 fallback。若 libass 实际日志表明选用了另一文件/face，像素预检失败。glyph
覆盖检查和实际 libass 选择都必须通过，不能只依赖其中之一。

## 14. 像素预检

完整成片编码前，使用实际 FFmpeg/libass、字体和 ASS，对每个 cue 的中点时间在透明 RGBA
画布上渲染一帧。预检不读取源视频画面，因此不会把背景像素误判成字幕。

每个 cue 必须：

- 产生非空 alpha 像素；
- 字幕 alpha bounding box 完整位于安全区域；
- 没有第5行或 libass 新增的意外行；
- 使用预期字体 face，无 fallback；
- 中英文样式颜色、字号和顺序与 plan 一致。

预检图像不是 v1 规范发布工件。adapter 应通过 pipe/内存读取帧，避免生成需要清理的图片文件；
libass读取ASS需要seek，因此正式执行允许在像素预检前先将ASS写入同文件系统staging，
此时绝不发布正式文件；dry-run仍只在内存验证ASS，不建staging也不写文件。
若外部工具失败后留下 staged 文件，保留并报告，不自动删除。正式、历史生成资产和任何残留
均只能在用户明确确认后删除。

## 15. FFmpeg 命令与执行

语义等价的规范命令为：

```bash
ffmpeg \
  -i video.mp4 \
  -vf "ass=bilingual.ass:fontsdir=<exact-font-directory>" \
  -map 0:v:0 \
  -map '0:a?' \
  -sn -dn \
  -c:v libx264 \
  -crf 18 \
  -preset medium \
  -pix_fmt yuv420p \
  -c:a copy \
  -fps_mode:v passthrough \
  -map_metadata 0 \
  -map_chapters 0 \
  -movflags +faststart \
  -n \
  <staged-output.mp4>
```

实现必须：

- 使用 argv 数组调用共享 `run_process()`，不经 shell；
- 对 FFmpeg filter 语法中的 ASS/font 路径单独正确转义；
- 优先在受控 staging 目录使用固定、安全的相对 ASS 文件名，减少 filter path 注入面；
- 输出到同文件系统的唯一临时文件，不直接写正式成片；
- 使用 `-n`，不使用 `-y`；
- 保留输入主视频、全部音频、metadata 和 chapters，不复制软字幕或 data stream；
- 不使用 `-shortest` 截断音频或视频；
- 音频无法原样封装到 MP4 时受控失败，不静默 AAC 转码；
- 不启用 VideoToolbox、CUDA 或其他硬件编码。

## 16. 成片验证

FFmpeg 返回0只是必要条件。对 staged MP4 重新 ffprobe，至少验证：

- 文件存在且非空，容器可解析；
- 恰有一个规范主视频流，codec 为 H.264；
- 宽高、SAR/DAR、旋转解释、平均帧率和像素格式符合输入/profile；
- 视频流时长与源视频流时长差不超过一个平均帧；
- 音频流数量、codec、采样率、声道数/布局与输入一致；
- 没有软字幕流和 data stream；
- 最后一条 cue 不超过输出视频可用时长；
- probe 输出、执行 argv、工具版本与 plan/manifest identity 一致。

平均帧率只能用于容差，不宣称逐帧精确。可变帧率或缺失流时长无法可靠比较时，不猜测成功，
而是返回 `render_validation_failed`。

## 17. Dry-run、复用、覆盖与并发

### 17.1 Dry-run

dry-run 可以执行只读文件验证、ffprobe、字体读取/测量和内存中的 ASS/布局验证，但不：

- 写 plan、ASS、report、manifest 或临时 MP4；
- 执行完整视频编码；
- 改变已有工件 mtime；
- 为获得命令而放宽输入或 artifact conflict。

逐 cue libass 像素预检会创建外部进程和临时帧，不属于严格零外部执行。因此 dry-run 只完成
确定性测量预检；正式执行在编码前完成实际 libass 像素预检。

### 17.2 复用 identity

复用绑定：

- SRT processing manifest、subtitle plan、video 的实际指纹；
- 上游整套证据仍可验证；
- rendering profile 内容指纹；
- 字体文件、face 和测量 adapter identity；
- pysubs2、FFmpeg、ffprobe、libass、libx264 精确版本；
- 输入媒体 probe、ASS 序列化和编码参数；
- plan、ASS、report、成片的实际指纹。

默认 `overwrite=false`：

```text
全套不存在                  -> 生成
全套存在且重新验证完全匹配  -> reused，零写入
只有部分文件                -> artifact_conflict
任一文件损坏                -> artifact_conflict
输入/profile/font/tool变化   -> artifact_conflict
```

复用时重新执行只读输入门禁、plan/ASS round-trip、report 重算和输出 ffprobe；不运行像素预检或
视频编码，不调用 clock，不更新 manifest 或 mtime。

`overwrite=true` 才允许替换本阶段整套正式输出。它不修改视频源、ASR、alignment、translation、
subtitle plan 或三份 SRT。

### 17.3 中断与并发

v1 不实现编码 checkpoint，无法从部分 MP4 继续。中断时没有成功 manifest；再次运行从完整
编码开始。失败临时文件不成为正式工件。若最佳努力发布了规范 failed report，之后运行需要
显式 `overwrite=true`，与 SRT processing 的保守冲突语义一致。

模块不实现资产锁。同一 asset 的两个直接调用不受支持；未来 orchestration 必须串行调度。

## 18. Manifest-last 发布

正式执行顺序固定为：

1. 验证输入与现有输出状态；
2. 在内存构造 render plan 与 ASS；
3. 完成字体、布局、ASS round-trip；在同文件系统暂存ASS并读回，再用该文件完成逐cue libass像素预检；
4. 将plan写入同文件系统staged文件并读回验证，ASS沿用已验证的暂存文件；
5. FFmpeg 写 staged MP4；
6. ffprobe staged MP4 并完成全套 QA；通过后才构造、暂存并读回成功report（2026-10-24用户批准），不预填尚未执行的媒体QA成功；
7. 计算四份正文输出证据；
8. 逐个原子发布 plan、ASS、成片和 report；
9. 最后构造、暂存、读回并原子发布成功 manifest。

多文件 rename 不是整体事务。崩溃可能留下部分新文件和旧/缺失 manifest；下次运行必须按
完整证据判定冲突，不能把文件存在视为完成，也不自动删除残留。

## 19. 错误分类

| 类别 | 含义 |
|---|---|
| `input_invalid` | 上游 schema、规范路径、身份或证据不合法。 |
| `artifact_conflict` | 已有正式工件不完整、损坏或不能按当前身份复用。 |
| `font_invalid` | 字体缺失、hash/face/family 不符、缺 glyph 或发生 fallback。 |
| `layout_failed` | 固定样式下无法在行数和安全区域内无损排版。 |
| `ass_generation_failed` | ASS 生成、纯文本转义或 round-trip 不保真。 |
| `tool_unavailable` | ffmpeg、ffprobe、libass 或 libx264 不可用。 |
| `render_failed` | FFmpeg 非零退出、超时或中断。 |
| `render_validation_failed` | staged 成片的媒体契约不成立。 |
| `publication_failed` | 已验证工件无法按 manifest-last 发布。 |
| `subtitle_rendering_failed` | 无法映射到以上类别的受控失败。 |

interface 只返回稳定的人类文案；底层异常、命令路径和 stderr 不直接成为公共错误消息。report
可以保存有长度上限的本地诊断，但不得因诊断写入失败掩盖原始错误。

## 20. 测试策略

### 20.1 默认离线测试

默认 pytest 不运行真实 FFmpeg、ffprobe 或系统字体。使用 fake store/font measurer/ASS codec/
probe/renderer/clock，覆盖：

- profile 序列化、hash 和严格字段；
- 640×360及其他分辨率的 round-half-up 缩放；
- 中文1/2行、英文1/2行、总计4行与无解布局；
- combining characters、emoji、Latin专名、数字单位、开放/闭合标点；
- 候选枚举顺序扰动下的确定性；
- ASS 中 `{\pos}`、`\N`、`\h`、反斜线、大括号和HTML类似正文；
- 全部上游输入/输出损坏、缺失、混合代次和 plan identity 错误；
- dry-run 零写入、复用零写入、overwrite 和 clock 不调用；
- font/hash/face/glyph/fallback 失败；
- FFmpeg argv、路径转义、音频映射和禁止 `-y`；
- staged 输出 probe 异常；
- 每个发布位置故障以及 manifest-last；
- 失败 report 不覆盖既有成功工件。

最终实现必须运行：

```bash
python -m pytest tests/ -q
```

### 20.2 本地真实技术集成：消费上游集成产物，必须交付样片

本模块的真实集成测试必须使用 transcription、translation、srt_processing 三个模块真实集成
验收留下的、属于同一资产和同一来源链的正式工件作为输入。不得用单元测试 fake、合成媒体、
手写字幕或来自不同测试 fixture 的文件拼出“集成通过”。

#### 20.2.1 输入产物及当前可用来源

固定样本为 `cnbc:2000:morning`，CNBC 2000 上午场连续第6、7节：当前623秒、2 sections、
97 sentences。三个阶段的输入关系如下：

| 来源阶段 | 本模块使用的产物 | 当前真实来源 |
|---|---|---|
| transcription 集成 | `video.mp4`、`source_alignment.json`、`transcription_manifest.json` 及证据链引用工件 | `tests/transcription/test_integration_live.py` 的持久 CNBC workspace：`output/transcription-integration/cnbc_2000_morning/`。 |
| translation 真实集成验收 | `translation_result.json`、`translation_manifest.json` | [SP-08A](../archive/tasks/SP-08A-prepare-persistent-cnbc-translation.md) 已通过现有生产 workflow 在同一 CNBC alignment 上生成并持久保存的97句/2 sections译文。 |
| srt_processing 集成 | `subtitle_plan.json`、三份 SRT、`srt_processing_report.json`、`srt_processing_manifest.json` | `tests.srt_processing.candidate_v3_runner` 的隔离 workspace：`output/cue-evaluation/20261023-candidate-v3/workspaces/cnbc_2000_morning/`，当前163 cues。 |

`tests/translation/test_integration_live.py` 当前使用 `synthetic:translation:live` 合成 alignment，
输出也位于 pytest 临时目录；它不是该 CNBC 样片的译文来源，不能冒称已经与 transcription
产物串联。这里复用的是 SP-08A 已记录的真实 translation 集成验收产物，而不是重跑该合成
fixture。未来若替换 fixture，必须重新证明同一视频/alignment/译文/plan 的来源链。

v3 workspace 已保留上述链条的复制/链接输入以及显式路径重定位证据。本模块从该 workspace
读取已验证的上游工件，不能再次改写或重定位 manifest 来“修复”输入。必须执行第7节门禁，
并交叉确认：

- transcription、translation 和 SRT manifest 的资产身份一致；
- 实际 alignment SHA-256 同时匹配 translation result/manifest 和 SRT plan/manifest；
- 实际译文 SHA-256 同时匹配 translation manifest 和 SRT plan/manifest；
- 实际视频 SHA-256 同时匹配 transcription 与 SRT 的证据；
- 2 sections、97 sentences、163 cues 的样本基线一致，完整正文与时间轴没有被重新生成。

这些数量是当前 fixture 的回归断言，不是生产模块的通用限制。换样本必须显式更新测试基线。

#### 20.2.2 执行入口和前置条件

实现 `tests/subtitle_rendering/sample_runner.py` 和调用它的本地集成测试，二者调用实际生产
composition/handler，不通过 fake renderer。真实 FFmpeg 集成不归类为网络 `live` 测试：

- pytest 入口由 `RUN_SUBTITLE_RENDERING_INTEGRATION=1` 显式开启；未开启时默认离线套件跳过。
- sample runner 由显式 `--run` 开启；它不是 CLI 或全管线入口。
- 两者默认只读取已有上游工件，不运行其他模块的 pytest、下载、ASR、translation/provider
  或 SRT planner；缺少输入时不得自动补跑昂贵阶段。
- 显式运行后缺少前置文件，runner 返回非零 `precondition_missing` 和缺失路径列表；pytest
  应失败，不能 skip 或报告 passed。损坏、身份不匹配也必须失败，不伪造产物或降级成合成测试。
- 如确需重新准备上游，先按各模块现有显式集成入口单独运行并交接匹配的正式产物；本测试
  只负责渲染集成，不承担上游恢复或 orchestration。

运行前验证：

```bash
ffmpeg -hide_banner -filters | awk '$2 == "ass" || $2 == "subtitles"'
ffprobe -version
```

#### 20.2.3 必须持久交付可播放样片

本集成测试必须实际烧录并保留 `video_中文字幕.mp4`，不能只输出 JSON、ASS、截图或 dry-run
命令。样片就是第8节的规范渲染视频，不另造只供测试使用的 MP4 格式或文件名。

默认 `output_root` 为 `output/cue-evaluation/20261023-candidate-v3/workspaces/`，用
`build_asset_workspace()` 和规范文件名得到：

```text
output/cue-evaluation/20261023-candidate-v3/workspaces/cnbc_2000_morning/
├── ...上游集成产物（只读，不覆盖）
├── subtitle_rendering_plan.json
├── bilingual.ass
├── video_中文字幕.mp4                 <- 必须持久保留的双语样片
├── subtitle_rendering_report.json
└── subtitle_rendering_manifest.json
```

- 首次仅新增本阶段五份文件；不覆盖既有上游工件、历史 v1/v2 或参考文件。
- 样片覆盖原有623秒完整集成样本及全部163 cues，保留音频；不通过 `-ss` / `-t` 截成其他
  片段，不修改源 cue 时间来制造短预览。
- 成片不得仅存在于 pytest `tmp_path` 或退出即清理的目录；生成资产位于 gitignored `output/`，
  不提交媒体文件，也不在测试结束后自动删除。
- runner 和测试交付证据必须给出解析后的绝对样片路径、字节数、SHA-256、探测时长、cue 数、
  manifest/report 路径、上游来源与输入指纹，便于不熟悉项目的人直接定位播放。
- 已有完整且同身份的样片可返回 `reused`，但首次技术验收必须记录真实 `succeeded` 的编码
  证据；只复用或 dry-run 不能替代首次样片生成。

#### 20.2.4 验收顺序

1. 前置门禁和全量上游 bytes/mtime 快照，确认本阶段五份输出尚不存在；
2. 首次运行实际字体、ASS、libass、FFmpeg 和 ffprobe，返回 `succeeded` 并持久发布样片；
3. 检查样片文件、成功 manifest、时长、音视频流、全部 cue 及像素 QA，保存样片交付证据；
4. 同进程第二次 `reused`，独立进程再次 `reused`；
5. 五份正式输出 bytes/mtime 不变，复用写入次数及视频编码调用均为0；
6. 三个上游模块的原始文件、v3输入文件及其链接目标 bytes/mtime 全部不变；
7. 人工播放样片，观看最长中英文、四行、专名、数字、首尾 cue、底部画面复杂场景及
   S17/S22/S48/S74/S88 等已知位置，记录可读性、遮挡、字幕闪烁和音画对应问题。

样片编码/发布/验证失败，或未能保留可播放样片时，本模块真实集成验收不通过；不得因已有
ASS、测试全绿或进程退出0就宣称样片交付。人工播放与出版质量签字仍按第22节区分。

## 21. 实施切片

实现按以下小步推进，每步只触及所需模块并做定向验证：

1. `SR-01`：`archive_core` rendering 工件类型、DTO、严格序列化与契约测试；
2. `SR-02`：render profile、缩放、纯布局和 domain QA；
3. `SR-03`：字体、ASS adapter、转义和像素测量；
4. `SR-04`：FFmpeg 命令、probe、renderer 适配器；
5. `SR-05`：输入门禁、workflow、复用、发布与公共 handler；
6. `SR-06`：跨层、对抗、故障注入和完整离线验收；
7. `SR-07`：串联消费 transcription/translation/SRT 真实集成产物，隔离 CNBC v3 真实烧录并
   持久交付可播放样片、首次生成证据、零写复用和人工视觉报告。

建议提交格式：

```text
feat(archive_core): add subtitle rendering contracts
feat(subtitle_rendering): build deterministic bilingual ASS plans
feat(subtitle_rendering): render and validate review videos
```

每个改变实现状态的提交必须同步根 `AGENTS.md` 和本模块 `AGENTS.md` 的事实与核对时间。

## 22. 完成定义与质量边界

只有同时满足以下条件，模块才能从“脚手架”改为“已实现”：

- 公共 DTO、规范文件名和 profile 已实现并测试；
- 默认测试不依赖真实外部二进制或系统字体；
- 完整离线 pytest 全绿；
- ASS 对每个 cue 都能无损追溯至 `SubtitlePlanDTO`；
- 所有 cue 的实际 libass 像素位于安全区域；
- 真实 FFmpeg 烧录和输出 ffprobe 通过；
- 集成测试输入来自同一资产的 transcription/translation/SRT 真实集成产物，且已持久交付可
  播放的完整双语样片与绝对路径/指纹/时长证据；
- 真实样本完成 `succeeded -> reused -> reused`；
- 复用时正式输出 bytes/mtime 不变且零写入；
- 上游视频、alignment、translation、plan 和 SRT 不变；
- 人工视觉审看报告已保存并明确剩余问题。

即使以上全部通过，也只证明 rendering 技术完成。ADR-0003 已披露的中英语义错位、节奏、专名
和翻译问题不会因烧录而消失；除非另有明确的人类签字，不得称为出版级字幕质量通过。

## 23. 已拒绝的替代方案

| 方案 | 拒绝原因 |
|---|---|
| 直接烧录 `bilingual.srt` | 会丢失权威语言字段、视觉断点 provenance 和精确样式控制。 |
| 只按字符数判断宽度 | 中文、Latin、数字和不同 glyph 的真实像素宽度不同。 |
| 交给 libass 自动换行 | 无法稳定控制行数、断点和回读 identity。 |
| 超宽时按 cue 缩字 | 造成同一成片字号跳变，且隐藏上游/样式不适配。 |
| 超宽时截字或改译文 | 破坏权威正文和来源覆盖。 |
| 使用 font family 自动搜索 | 同名 family 可解析到不同文件或 fallback，结果不可复现。 |
| 随仓库提交 Hiragino 字体 | 系统专有字体，不应复制或重新分发。 |
| 默认 AAC 音频转码 | 无必要地损失音质并改变已有音频；不兼容应显式决策。 |
| 默认硬件 H.264 | 设备、驱动和质量行为差异大，不适合作为规范输出。 |
| 仅以 FFmpeg 返回0判成功 | 不能发现空视频、流丢失、时长和像素格式变化。 |
| 视频存在即复用 | 不能证明输入、字体、参数、工具或其他输出仍匹配。 |
| 先实现 orchestration/CLI | 会让薄接口依赖未冻结的 rendering 契约。 |

## 24. 实现状态

### 24.1 当前状态（2026-10-24）

- SR-01..06已验收并移入[归档任务目录](../archive/tasks/README.md)，公共契约、确定性布局、
  字体/ASS/像素/媒体adapter、工作流与独立对抗测试均已实现。
- SR-07 runner及显式本地集成已实现；623秒/163cue同源完整样片已持久生成并通过
  `succeeded → reused → reused`、逐cue像素/媒体QA、零写复用与全部上游不变检查。
- 负责人最近独立完整离线为2580 passed / 6 skipped，真实本地集成复用1 passed。
- 用户实际播放发现中文内容与英语讲话语义不同步；SR-07最终验收未通过，不能据技术通过
  归档本ADR为完成。用户后续确认其观察中的英文逐词时间准确，当前问题优先归于中文分块/
  比例词区间映射，保留transcription，不在rendering中私改cue。
- [复审报告](../reviews/2026-10-24-rendering-technical-and-semantic-review.md)保存样片指纹和
  用户反馈。新的语义对齐方案尚未接受，也未实施；下文为决策接受时的历史快照。

### 24.2 接受时历史状态

截至本 ADR 接受时：

- 决策已由用户确认；此前待决策项均采用推荐方案。
- 用户补充确认本模块集成测试必须复用上述三个上游模块真实集成产物，并输出持久可播放
  样片；本次仅补充决策，尚未实现或运行该测试、尚未生成样片。
- `subtitle_rendering` 仍无生产代码、公共 rendering DTO、ASS、成片或真实验收。
- 本机已核实 FFmpeg 9.0.1 来自 `ffmpeg-full`，含 `ass`、`subtitles`、libass、libx264；CNBC
  样本为640×360、30fps、H.264、`yuv420p`、623秒。
- 已核实当前系统字体文件、SHA-256及W3/Regular为TTC index 0；实现中的字体 adapter 仍必须
  独立验证，不能信任配置本身。
- 本 ADR 的接受不改变根状态表中的“脚手架”结论。
