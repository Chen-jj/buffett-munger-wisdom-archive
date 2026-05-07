# buffett-munger-wisdom-archive

巴菲特与芒格思想相关演讲视频的抓取、英文字幕生成、中文翻译、硬字幕烧录与审看工具。

> 本文档聚焦当前仓库**仍然成立的能力、约束和使用方式**，尽量避免写容易快速过期的过程性信息。

## 1. 项目概览

本仓库围绕巴菲特与芒格思想相关演讲视频，提供一套可复用的处理流程。当前已覆盖伯克希尔年度股东大会视频，后续可扩展到更多巴芒相关演讲、访谈与 archive 素材：

1. 抓取页面、章节、逐字稿与元数据
2. 下载视频
3. 提取音频并生成英文 SRT
4. 生成中文 SRT
5. 烧录硬字幕视频
6. 生成 review 报告并提供 Web 审看

当前仓库同时包含：

- 一套原始流水线入口：`run.py`
- 一套更适合日常处理与调试的增强 CLI：`tools_project_cli.py`

如果你的目标是：

- 做样片
- 调试字幕
- 做烧录 review
- 启动本地审看页面

优先使用 `tools_project_cli.py`。

## 1.1 CLI 启动方式

最常用的进入方式：

```bash
cd /Volumes/extender/CodeBase/buffett-munger-wisdom-archive
. .venv/bin/activate
python3 tools_project_cli.py -h
```

如果本地还没有虚拟环境，可先初始化：

```bash
cd /Volumes/extender/CodeBase/buffett-munger-wisdom-archive
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 tools_project_cli.py -h
```

日常使用通常从查看可用资产开始：

```bash
python3 tools_project_cli.py list --year 1994
```

## 2. 当前项目原则

### 2.1 英文时间轴优先来自 Whisper 精校音频链路

当前英文 SRT 的主生成入口是 `src/step2_align.py`。

继续维护时，优先保证：

- 英文字幕时间轴来自 Whisper 精校音频链路
- 中文字幕沿用对应英文时间轴
- 不再引入额外的全局 offset 同步逻辑

### 2.2 不要把旧字幕文件默认当作最新基准

仓库里可能同时存在：

- 较早阶段生成的英文 SRT
- 后续样片生成的英文 SRT
- 不同目录下的中文 SRT

继续处理前，先确认当前要使用的是哪一版字幕文件。

### 2.3 `burn-from-srt` 默认会生成 review

当前 `tools_project_cli.py burn-from-srt` 在烧录后会自动生成：

```text
<output>.review.json
```

review 目前主要做结构性校验，不等同于音频级自动同步评分；字幕同步本身以 Whisper 精校结果为主。

## 3. 目录结构

```text
buffett-munger-wisdom-archive/
├── README.md
├── Agent.md
├── handoff.md
├── config.yaml
├── requirements.txt
├── run.py
├── tools_project_cli.py
├── src/
│   ├── step0_crawl.py
│   ├── step1_download.py
│   ├── step2_align.py
│   ├── step3_translate.py
│   └── step4_burn.py
├── input/
└── output/
```

`output/` 下会按年份和 session 继续展开，保存视频、音频、字幕、样片、review 报告等产物。

## 4. 核心模块

## 4.1 抓取：`src/step0_crawl.py`

负责抓取：

- 年份页与 morning / afternoon session 链接
- 逐字稿章节结构
- 页面元信息

典型产物：

- `output/<year>/metadata.json`
- `output/<year>/<session>/chapters.json`
- `output/<year>/<session>/transcript.txt`
- `output/<year>/<session>/meta.json`

## 4.2 下载：`src/step1_download.py`

负责解析实际媒体地址并下载视频，典型输出为：

- `output/<year>/<session>/video.mp4`

## 4.3 英文 SRT：`src/step2_align.py`

负责从视频或音频生成英文字幕。

当前维护时要特别注意两点：

1. `align_year()` 遇到已存在的 `english.srt` 会跳过，不会自动覆盖
2. 如果需要重建，建议先输出到新文件名，例如 `english.precise.srt`

示例：

```bash
. .venv/bin/activate
python src/step2_align.py \
  --audio output/1994/morning/audio.wav \
  --output output/1994/morning/english.precise.srt
```

## 4.4 中文 SRT：`src/step3_translate.py` + `tools_project_cli.py`

当前支持三类常见方式：

### 方式 1：直接翻译 SRT

```bash
. .venv/bin/activate
python tools_project_cli.py translate-srt input.srt output.srt
```

### 方式 2：导出批次，再合并

```bash
. .venv/bin/activate
python tools_project_cli.py export-batch input.srt out_dir --batch-size 80
python tools_project_cli.py merge-batch out_dir output.srt
```

### 方式 3：heuristic fallback

```bash
. .venv/bin/activate
python tools_project_cli.py translate-srt-heuristic input.srt output.srt
```

适合流程验证，不适合正式交付。

## 4.5 烧录：`src/step4_burn.py` + `tools_project_cli.py`

当前仓库里仍然有两条相关路径：

- `src/step4_burn.py`：原始烧录实现
- `tools_project_cli.py burn-from-srt`：当前更常用的工作流入口

`burn-from-srt` 的当前策略是：

1. 读取 SRT
2. 按需裁切样片
3. 优先使用 ffmpeg 字幕 filter 烧录
4. 缺少相关能力时 fallback 到 PNG overlay
5. 自动生成 review 报告

示例：

```bash
. .venv/bin/activate
python tools_project_cli.py burn-from-srt video.mp4 chinese.srt out.mp4 --duration 00:15:00
```

## 4.6 review：`review-burn`

当前 review 主要检查：

- 使用的字幕文件
- 若干时间信息与 gap 保留情况
- 当前烧录模式
- 输出文件是否存在
- 输出时长与体积是否明显异常

注意：

- 它适合做结构性验收
- 不能完全替代人工同步抽检

## 4.7 Web 审看：`serve-review`

`tools_project_cli.py serve-review` 会启动本地 Web 审看界面，当前能力包括：

- 按年份查看视频目录
- 查看 session 列表
- 查看章节 / 问答导航
- 点击跳转视频时间点
- 查看当前章节的中文内容
- 收藏章节

示例：

```bash
. .venv/bin/activate
python tools_project_cli.py serve-review --port 8765 --open
```

## 5. 推荐工作流

### 工作流 A：查看资产

```bash
. .venv/bin/activate
python tools_project_cli.py list --year 1994
```

### 工作流 B：确认英文 SRT 来源

必要时输出到新文件：

```bash
. .venv/bin/activate
python src/step2_align.py \
  --audio output/1994/morning/audio.wav \
  --output output/1994/morning/english.precise.srt
```

### 工作流 C：生成中文 SRT

```bash
. .venv/bin/activate
python tools_project_cli.py translate-srt input.srt output.srt
```

### 工作流 D：生成样片并自动 review

```bash
. .venv/bin/activate
python tools_project_cli.py burn-from-srt video.mp4 chinese.srt out.mp4 --duration 00:15:00
```

### 工作流 E：启动 Web 审看

```bash
. .venv/bin/activate
python tools_project_cli.py serve-review --port 8765 --open
```

## 6. 常用命令

## 6.1 原始主流程

```bash
. .venv/bin/activate
python run.py --year 1994
python run.py --year 1994 --step 2
python run.py --year-range 1994 1995
```

## 6.2 CLI 资产与文本工具

```bash
. .venv/bin/activate
python tools_project_cli.py list --year 1994
python tools_project_cli.py read output/1994/morning/english.srt --max-chars 2000
python tools_project_cli.py srt2json output/1994/morning/english.srt
python tools_project_cli.py clean-srt input.srt output.cleaned.srt
python tools_project_cli.py clip-srt input.srt output.clip.srt --duration-sec 900
python tools_project_cli.py translate-preview output/1994/morning/english.srt --start 1 --count 12
```

## 6.3 翻译相关

```bash
. .venv/bin/activate
python tools_project_cli.py translate-srt input.srt output.srt
python tools_project_cli.py translate-srt-heuristic input.srt output.srt
python tools_project_cli.py export-batch input.srt out_dir --batch-size 80
python tools_project_cli.py merge-batch out_dir output.srt
```

## 6.4 烧录 / review / 审看

```bash
. .venv/bin/activate
python tools_project_cli.py burn-from-srt video.mp4 chinese.srt out.mp4 --duration 00:15:00
python tools_project_cli.py review-burn video.mp4 clipped.srt out.mp4
python tools_project_cli.py serve-review --port 8765 --open
```

## 6.5 清理旧输出

```bash
. .venv/bin/activate
python tools_project_cli.py cleanup-output --dry-run
python tools_project_cli.py cleanup-output
```

## 7. 环境与依赖

当前仓库能直接看到的依赖来源包括：

- `requirements.txt`
- `src/step2_align.py` 的相关 Python 依赖
- `tools_project_cli.py` 的相关 Python 依赖
- 系统工具：`ffmpeg`、`ffprobe`、`yt-dlp`

推荐初始化方式：

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
```

如果后续执行某些步骤仍提示缺包，再按对应模块补装依赖。

系统工具可这样检查：

```bash
ffmpeg -version
ffprobe -version
yt-dlp --version
```

## 8. 配置说明

关键配置在 `config.yaml`。

继续维护时，优先关注两类配置：

- 翻译相关配置
- 对齐 / 运行设备相关配置

如果修改默认模型、设备、批大小或接口地址，记得同步更新文档。

## 9. 已知限制

1. `run.py` 与 `tools_project_cli.py` 仍代表两套并行能力，尚未完全统一
2. `align_year()` 不会覆盖已存在的 `english.srt`
3. `requirements.txt` 与实际运行所需依赖可能仍有偏差
4. `cleanup-output` 目前更偏向定制清理，不是通用产物管理器
5. review 当前仍以结构校验为主，不是音频级自动同步打分器

## 10. 更多交接信息

更多上下文请看：

- `Agent.md`
- `handoff.md`
