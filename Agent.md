# Agent.md

本文件给下一位接手本仓库的 Agent 提供最小但足够的项目上下文。

## 1. 当前目标

这个仓库当前的主线已经比较明确：

1. 抓取伯克希尔股东大会页面与元数据
2. 下载视频并提取音频
3. 生成英文 SRT
4. 生成中文 SRT
5. 烧录硬字幕视频
6. 提供 review 与 Web 审看能力
7. 让后续年份可以复用同一套流程

## 2. 当前必须记住的原则

### 2.1 当前字幕已经以 Whisper 精校结果为准

当前字幕时间轴已经以 Whisper 精校链路为准，不再需要额外的全局 offset 同步方案。

后续如果发现问题，优先检查：

- 英文 SRT 的来源是不是旧产物
- `src/step2_align.py` 的输出是否被真正使用
- 当前样片是不是沿用了旧字幕而不是新字幕

### 2.2 英文时间轴优先来自 Whisper 精校音频链路

当前仓库里，英文 SRT 的可靠来源是 `src/step2_align.py`。

不要默认回退到：

- transcript 文本长度估时
- 事后再补一个固定 offset

### 2.3 `burn-from-srt` 默认会生成 review

继续开发时：

- 不要绕过 review
- 如果修改烧录链路，要保证 review 还会继续产出

### 2.4 review 目前主要是结构校验

当前 review 更适合回答：

- 输出文件是否生成成功
- 字幕 gap 是否保留
- 输出时长 / 文件大小是否明显异常
- 当前使用了哪种烧录模式

它还不能单独证明：

- 字幕与语音一定已经做到音频级精确同步

所以如果后续继续增强同步验证，这仍然是一个值得继续做的方向。

## 3. 当前项目事实

### 3.1 仓库里仍然有两套入口

- `run.py`：原始按步骤执行的流水线入口
- `tools_project_cli.py`：当前更常用的增强 CLI

如果是继续调试字幕、生成样片、做 review、启动 Web 审看，优先看 `tools_project_cli.py`。

### 3.2 当前烧录策略是 filter-first，必要时 fallback

现在 `tools_project_cli.py burn-from-srt` 默认优先走 ffmpeg 字幕 filter；缺少相关能力时再 fallback 到 PNG overlay。

因此后续判断烧录行为时，不要再按“默认总是 PNG”理解。

### 3.3 当前最可信的样片基准仍在 `output/1994/morning/render2/`

关键文件：

- `output/1994/morning/render2/english_15min.srt`
- `output/1994/morning/render2/chinese_15min_full.srt`
- `output/1994/morning/render2/1994_morning_15min_review.mp4`
- `output/1994/morning/render2/1994_morning_15min_review.mp4.review.json`

不要默认把 `output/1994/morning/english.srt` 当成最新最准的基准。

### 3.4 `align_year()` 不会覆盖已有 `english.srt`

如果直接跑：

```bash
python src/step2_align.py --year 1994
```

已存在的 `english.srt` 会被跳过。

因此如果怀疑旧英文 SRT 不够准确，通常应该：

- 输出到新文件名，例如 `english.precise.srt`
- 验证后再决定是否替换旧文件

## 4. 推荐的默认工作顺序

### 顺序 A：先确认输入是不是旧产物

重点看：

- `output/1994/morning/english.srt`
- `output/1994/afternoon/english.cleaned.srt`
- `output/1994/morning/render2/english_15min.srt`

### 顺序 B：需要时重建英文 SRT

示例：

```bash
. .venv/bin/activate
python src/step2_align.py \
  --audio output/1994/morning/audio.wav \
  --output output/1994/morning/english.precise.srt
```

### 顺序 C：再生成中文 SRT

直接翻译：

```bash
. .venv/bin/activate
python tools_project_cli.py translate-srt input.srt output.srt
```

批量导出 / 合并：

```bash
. .venv/bin/activate
python tools_project_cli.py export-batch input.srt out_dir --batch-size 80
python tools_project_cli.py merge-batch out_dir output.srt
```

### 顺序 D：先做样片，再做整场

```bash
. .venv/bin/activate
python tools_project_cli.py burn-from-srt \
  output/1994/morning/video.mp4 \
  output/1994/morning/render2/chinese_15min_full.srt \
  output/1994/morning/render2/1994_morning_15min_review.mp4 \
  --duration 00:15:00
```

### 顺序 E：用 Web 审看人工验收

```bash
. .venv/bin/activate
python tools_project_cli.py serve-review --port 8765 --open
```

## 5. 你最该优先看的文件

### 第一优先级

- `src/step2_align.py`
- `tools_project_cli.py`
- `src/step4_burn.py`

### 第二优先级

- `src/step3_translate.py`
- `run.py`
- `config.yaml`

### 第三优先级

- `output/1994/...` 里的真实产物

## 6. 完成改动后的最低验收标准

如果你修改了对齐 / 翻译 / 烧录 / review 任一环节，至少要做到：

1. 代码可运行
2. `python -m py_compile ...` 通过
3. 不重新引入固定全局 offset 方案
4. 如果行为变了，README / handoff / Agent 文档同步更新

## 7. 建议的第一条自检命令

```bash
. .venv/bin/activate && python tools_project_cli.py list --year 1994
```

然后再看：

- `README.md`
- `handoff.md`
