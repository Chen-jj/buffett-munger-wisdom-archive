# srt_processing AGENTS.md

## 模块定位

`srt_processing` 负责字幕结构、SRT 解析/写出、保时序变换、双语合成，以及字幕 QA。

## 职责

- 解析、规范化、拆分、合并、写出 SRT，同时保持序号与时序不变。
- 校验字幕编号、时间戳单调性、重叠、空条目、时长异常。
- 合成双语字幕表示，不与渲染样式耦合。
- 为翻译与评审提供可复用的文本分段工具。

## 分层规则

- `domain/`：字幕 cue、时间区间、字幕文档、校验发现、变换策略。
- `application/`：validate-srt、repair-structure、merge-bilingual、split-for-translation、compare-subtitles 用例。
- `infrastructure/`：`pysubs2` 适配器与文件系统编解码。
- `interfaces/`：CLI 处理器、评审 DTO、面向渲染/翻译的契约。

## 技术方向

- `pysubs2` 只作为适配器，不作为领域模型。
- 翻译服务调用不得进入本模块；本模块只准备与校验文本单元。
- ASS 样式不得进入本模块；呈现样式归渲染所有。
