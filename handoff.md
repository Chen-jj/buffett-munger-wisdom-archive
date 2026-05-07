# handoff

本文档用于在重启 Agent 对话后快速恢复上下文。

## 1. 交接时间

- 日期：2026-04-30
- 工作目录：`/Volumes/extender/CodeBase/buffett-munger-wisdom-archive`

## 2. 当前已经完成的事情

### 2.1 字幕精校主线已经跑通

目前仓库已经完成并验证过一轮“英文字幕生成 -> 中文字幕 -> 样片烧录 -> review”的主流程。

当前不需要再把重点放在“是否已经具备字幕精校能力”这个问题上，重点更适合放在：

- 继续复用这条链路处理更多内容
- 清理旧产物带来的混淆
- 让文档和现状保持一致

### 2.2 `burn-from-srt` 的默认工作流已经稳定

当前 `tools_project_cli.py burn-from-srt` 会：

- 读取 SRT
- 按需要裁切样片
- 优先使用 ffmpeg 字幕 filter 烧录
- 在必要时 fallback 到 PNG overlay
- 自动生成 `.review.json`

### 2.3 15 分钟样片仍可作为当前参考基准

关键参考产物仍然在：

- `output/1994/morning/render2/english_15min.srt`
- `output/1994/morning/render2/chinese_15min_full.srt`
- `output/1994/morning/render2/1994_morning_15min_review.mp4`
- `output/1994/morning/render2/1994_morning_15min_review.mp4.review.json`

## 3. 当前最重要的事实 / 不要遗忘

### 3.1 当前不再需要额外 offset 同步

当前字幕时间轴已经采用 Whisper 精校结果，不再需要单独讨论固定 offset 同步方案。

如果用户反馈同步问题，优先回到：

- 英文 SRT 来源
- 当前实际使用的字幕文件
- review 能否覆盖到对应问题

### 3.2 旧英文 SRT 不能默认视为最新基准

当前仓库里旧英文产物和样片英文产物并存。

尤其是：

- `output/1994/morning/english.srt`
- `output/1994/morning/render2/english_15min.srt`

两者不要混用，也不要默认前者一定是最新精确版本。

### 3.3 `align_year()` 依然不会覆盖已有 `english.srt`

如果直接跑：

```bash
python src/step2_align.py --year 1994
```

已有 `english.srt` 会被跳过。

需要重建时，建议输出到新文件名再做核对。

## 4. 当前仓库真实能力

### 4.1 原始入口

- `run.py`
- `src/step0_crawl.py`
- `src/step1_download.py`
- `src/step2_align.py`
- `src/step3_translate.py`
- `src/step4_burn.py`

### 4.2 增强 CLI

`tools_project_cli.py` 当前支持：

- `list`
- `read`
- `srt2json`
- `clean-srt`
- `translate-srt`
- `translate-srt-heuristic`
- `translate-preview`
- `export-batch`
- `merge-batch`
- `clip-srt`
- `burn-from-srt`
- `review-burn`
- `serve-review`
- `cleanup-output`

### 4.3 Web 审看能力

当前已实现：

- 年份折叠导航
- session 列表
- 章节 / 问答导航
- 点击跳转视频时间点
- 展示该轮中文内容
- 收藏功能
- 收藏数据落在 `webapp/app.db`

## 5. 当前建议关注的事项

### P0：继续保持文档与真实实现一致

文档里最容易过期的内容主要有：

- 把某些样片结果写成“最新结论”
- 把阶段性 TODO 写成仍未完成
- 把历史兼容策略写成当前默认行为

后续更新文档时，优先描述“当前能力”和“仍然成立的约束”，少写容易过期的过程性结论。

### P1：继续区分旧产物与当前产物

如果后续要继续做 1994 全量版本，或扩展到其他年份，仍然建议：

1. 先确认英文 SRT 来源
2. 再确认中文 SRT 是否对应同一版英文时轴
3. 最后再烧录与审看

### P1：review 仍然主要是结构校验

这一点没有变。

它已经足够支撑日常样片和产物检查，但如果未来要做更强的自动同步验收，仍然可以在此基础上增强。

## 6. 当前已知问题

### 问题 1：两套入口仍未完全统一

- `run.py` / `step4_burn.py` 偏原始流水线
- `tools_project_cli.py` 偏当前主力工作流

### 问题 2：`requirements.txt` 与隐式依赖未完全对齐

当前运行仍然依赖一些代码里使用、但未必完整声明的包与系统工具。

### 问题 3：review 不是音频级自动验收

它能发现结构问题，但仍不能完全替代人工同步抽检。

## 7. 继续工作时建议先跑的命令

### 查看现有资产

```bash
. .venv/bin/activate
python tools_project_cli.py list --year 1994
```

### 查看 CLI 帮助

```bash
. .venv/bin/activate
python tools_project_cli.py -h
```

### 如需重建英文 SRT，建议输出到新文件

```bash
. .venv/bin/activate
python src/step2_align.py \
  --audio output/1994/morning/audio.wav \
  --output output/1994/morning/english.precise.srt
```

### 启动 Web 审看

```bash
. .venv/bin/activate
python tools_project_cli.py serve-review --port 8765 --open
```

## 8. 如果下一个 Agent 只看一个文件

优先看：

1. `Agent.md`
2. `README.md`
3. 本文件 `handoff.md`

如果要改代码，优先看：

1. `src/step2_align.py`
2. `tools_project_cli.py`
3. `src/step4_burn.py`
