# SR-04 — 媒体探测、软件编码与流验证

- **Status:** accepted
- **Owner:** render_media 子开发 agent（负责人验收）
- **Depends on:** SR-01、SR-02 accepted
- **Depended on by:** SR-05

## 范围

只拥有rendering/infrastructure/probe.py、ffmpeg.py、相关测试；必要共享process二进制pipe支持须先报负责人并读infrastructure指南，最小兼容扩展不另写shell runner。按ADR第14–16节，工具/libass/libx264精确identity、argv/filter路径转义、同文件系统唯一staged MP4、-n/全部音频copy/metadata/chapters/passthrough/faststart，无硬件编码/-y/-shortest。

与SR-03冻结透明帧pipe和日志接口。probe严格验证可解释主视频、宽高/SAR/DAR/旋转/帧率/时长/pixfmt、全部音频；产物H264一视频、音频保持、无字幕/data、时长差≤一平均帧及最后cue覆盖。不可靠VFR/缺流时长受控失败。

## 验证/交接

fake process覆盖命令映射、特殊路径、空/非法probe、未知工具版本/缺filter/encoder、超时/中断、音频封装失败、输出流/时长/方向/pixfmt差异。默认测试不启动外部二进制。交API、定向命令结果与风险，负责人复验。

## 只读设计调查（2026-10-23）

负责人已批准下述方向，**尚未实现**；等待 SR-01、SR-02 accepted 后编码。

### API 与分工

- 公共媒体、字体、工具 DTO 以 SR-01 `archive_core.interfaces.rendering` 冻结类型为准。
- `FfprobeMediaProbe.probe(path)` 返回 `RenderMediaDTO`：严格媒体 JSON、首帧解码证据、全视频
  packet 节奏检查；`validate_rendered_media(source, output, last_cue_end_ms)` 做输出纯验证。
- `FfmpegRenderer` 提供工具 identity、规范 argv 规划、正式软件编码执行，以及每 cue 独立进程的
  `render_transparent_frame(ass_path, fonts_dir, width, height, time_ms)`；帧返回 RGBA bytes、宽高和
  完整有界 verbose stderr。日志超限必须失败，不截断关键 fontselect 后仍宣称通过。
- SR-03 消费透明帧与日志，负责 alpha bbox、行数/样式和字体 identity 验证；CoreText 实际日志可能
  使用 `index=-1` 和 PostScript name，不能机械要求 fontselect 日志 index 恒为 TTC index 0。
- 共享 `run_process()` 目前固定 `text=True`，不支持 RGBA bytes。负责人已批准最小追加独立
  `run_process_bytes` / bytes result API，保持原文本 API、runner 参数和现有调用完全不变；二进制
  stdout 不作为错误文案，timeout bytes 诊断需测试，不另写 subprocess/shell runner。

### 本机只读证据

调查未修改 `output/`，未运行 ASR、翻译、planner 或完整视频编码。

- `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` 与同目录 ffprobe 实际版本均为 9.0.1；构建包含
  libass 与 libx264。`ass` filter 帮助明确支持 `alpha=1`。
- 实际 libass 初始化日志为 API `0x1705000`、source `tarball: 0.17.5`，并报告 FreeType 2.14.3、
  FriBidi 1.0.16、HarfBuzz-ng 14.3.1；不能只把 FFmpeg build flag 当作 libass 精确版本。
- 下列命令只启动 libx264、输出 0 帧 MP4 到内存，stderr 可取得实际链接编码器
  `264 - core 165 r3222 b35605a`；`-f null` 不提供该精确版本。工具 identity 若采用此方式，须
  明确为零帧、零文件的工具探测，不能借此在 dry-run/reuse 执行完整视频编码。

  ```text
  ffmpeg -hide_banner -loglevel verbose -f lavfi -i color=size=2x2 -frames:v 0
    -c:v libx264 -f mp4 -movflags empty_moov pipe:1
  ```

- CNBC 真实 v3 workspace 视频 probe：640×360、SAR 1:1、DAR 16:9、H.264/yuv420p、平均/参考
  帧率均 30/1、视频时长 623000000µs、18690 帧；1 路 AAC、44100Hz、2 channels/stereo。
- `ffprobe -read_intervals '%+#1' -select_streams v:0 -show_frames` 实际解码返回 640×360/yuv420p
  视频帧。
- 全视频 packet 实测 18690 个，`time_base=1/15360`，所有 duration 均 512；PTS 排序后全部
  18689 个相邻间隔也均 512，PTS 范围 0..9568768。B-frame 会使原 packet 顺序的 PTS 非单调，
  所以必须排序后判定节奏，不能误报 VFR。仅 `r_frame_rate == avg_frame_rate` 不是 CFR 证明。

### 已报告风险与待确认

- 非正方像素、旋转/显示坐标不可解释、缺少视频流 duration、无法可靠判定 VFR 均应受控失败，
  不依赖容器 duration 猜测成功。
- font agent 已实测 libass ASS 文件读取需要 fseek，不能直接用 `/dev/stdin` 代替 seekable ASS。
  因此透明帧可 pipe，但像素预检必须读取真实 staged ASS。ADR 第18节原顺序先预检后暂存 ASS
  不可直接实现；负责人已向用户请求允许提前暂存 ASS。仍不正式发布、不改 dry-run 零写、失败
  保留残留并报告，manifest-last 不变；未获答复前不擅自改执行顺序。
- 默认测试应覆盖 PTS 编码顺序乱序但显示节奏恒定、均值相同但间隔可变的 VFR、packet 缺 PTS/
  duration、decode 返回空帧/错误、所有媒体/音频/章节及 metadata 差异、未知工具版本和日志超限。


## 开发交付（2026-10-24 00:35 CST，待负责人验收）

- 用户已批准提前在同文件系统暂存 ASS，正式像素预检读取该 staged ASS；dry-run 零写、失败
  保留残留和 manifest-last 不变。前文“待确认”仅记录当时调查状态。
- 实现 `infrastructure/probe.py`：`FfprobeMediaProbe.version()/probe(path)`、`parse_media` 和
  `validate_rendered_media(source,output,last_cue_end_ms)`；纯 Decimal→微秒，无 float 时间转换。
  `probe` 每次验证流、首帧实际 decode 和全视频 packet；PTS 排序，完整证明固定 duration/节奏，
  并核对 stream start/duration/frame_count，不以平均帧率冒充 CFR。`MediaProbeError` 由 workflow
  按输入/输出上下文映射 input_invalid 或 render_validation_failed，不一律误报工具缺失。
- 实现 `infrastructure/ffmpeg.py`：`FfmpegRenderer.tool_identity/build_command/render/
  render_transparent_frame`、`TransparentFrame`、双层 `escape_filter_path`。`RenderAdapterError`
  只公开稳定 category，最长 2048 字符 diagnostic 留给本地 report。规范命令保留 `-n`、
  libx264/CRF18/medium/yuv420p、全部音频 copy、metadata/chapters/passthrough/faststart；无重试转码。
- 透明输入使用 `format=rgba,trim=end_frame=1`，避免 libass 因 FFmpeg 请求第二帧而重复 line-break
  日志；显式 `settb=1/1000,setpts=PTS+<中点毫秒>`，不让 25fps 输入把中点量化到 40ms。每 cue
  独立 FFmpeg，debug fontselect/forced-line-break 日志完整保留，日志超限受控失败。像素/字体
  解释仍归 SR-03，适配器不假装仅“返回 raw bytes”就已经通过像素验收。
- 共享 process 只追加独立 bytes API，旧文本实现未修改；新增 bytes timeout/无 stdin/
  Unicode 诊断/dry-run/check 测试。`tests/subtitle_rendering/__init__.py` 修复与旧
  `tests/srt_processing/test_probe.py` 同名收集冲突，没有删除或改名旧测试。
- `tool_identity` 明确执行零帧 libx264 内存 MP4 初始化与只读空 ASS 初始化来获得实际运行库
  版本；不会做完整视频编码，也不写探测工件。未知版本、缺 filter/encoder、超时（即便已有
  部分版本日志）均不通过。FFmpeg/ffprobe 保存完整 version/config/library 文本，libass 保存
  API/source/实际 Raster/Shaper，libx264 保存 core/revision/hash/CPU capabilities。

### 验证

- 定向：`.venv/bin/python -m pytest tests/subtitle_rendering/test_probe.py
  tests/subtitle_rendering/test_ffmpeg.py tests/infrastructure/ -q` → **155 passed**。
- 完整离线：`.venv/bin/python -m pytest tests/ -q` → **2019 passed / 5 skipped**
  （并行 SR-03 测试已进入树；最终此轮无 warnings）。
- 新 adapter 实际只读探测同一 CNBC：623000000µs、18690帧、30/1、1路 AAC；实际 tool identity
  与调查版本一致。没有重跑上游或完整烧录。
- 新透明适配器实际读取 SR-03 scratch ASS 返回 640×360×4=921600 bytes、非空 alpha、正确
  HiraginoSansGB-W3 fontselect，四行仅三条 forced-line-break，不重复。
- 在 `/private/tmp/sr04-path-probe-1enhpl8c` 创建含空格/单引号/冒号/逗号/分号/方括号/反斜线的
  ASS 路径和 fontsdir symlink，实际 FFmpeg 成功渲染透明帧，双层路径转义已验证。scratch
  残留原样保留；没有改写 `output/`、删除文件或 commit。

### 已知保守限制

- 有 chapter 的 MP4 可能由 FFmpeg 生成 bin_data chapter stream；规范同时要求保留 chapters
  且无 data stream，本实现不豁免、不丢章，会严格返回验证失败。负责人同意记录此限制；
  当前 CNBC 无 chapters，不影响固定样片。
- 量化 time_base 导致 packet 间隔不能精确证明恒定、视频流 duration 缺失或显示坐标不明时
  都受控失败，不添加猜测兼容策略。
- 同文件系统唯一 staging 目录/输出路径由 SR-05 store/workflow 分配，renderer 不自行发明
  workspace 或提前发布正式视频；默认离线测试不执行外部工具或读取系统字体。

## 负责人验收（2026-10-24 00:33 CST）

已审argv/双层filter转义、零帧工具探测、透明RGBA中点/单帧、packet显示顺序/CFR、独立输出媒体QA及共享process兼容追加。独立复验本任务三新增测试文件133 passed，完整当前合并树2019 passed / 5 skipped（6.04s），diff check通过。SR-04 accepted；SR-05仍等待SR-03。有章MP4的data-track限制保留，未放宽契约。
