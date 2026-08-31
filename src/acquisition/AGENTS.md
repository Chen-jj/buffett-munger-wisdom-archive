# acquisition AGENTS.md

## 模块定位

`acquisition` 负责来源发现、抓取、来源页面解析、逐字稿提取、来源元数据规范化，以及采集工件的持久化。

## 架构

- `domain/` 只放来源无关的值对象；站点特定概念不得进入。
- `application/` 是来源无关的编排：一个用例接收采集请求，通过 registry 选择爬虫，发现目标、逐个抓取、可选持久化，返回结果列表。
- `infrastructure/` 放 HTTP、HTML 解析、元数据提取、逐字稿规范化、各站点爬虫、本地工件写入。

## 依赖规则

- 依赖只能向内指：infrastructure 依赖 application/domain 契约；application 依赖 domain 与 Protocol 端口；domain 只 import 纯原语与共享的 `archive_core` 身份值。
- domain 不得 import `requests`、`bs4`、文件系统 API、subprocess、UI，或其他模块的 infrastructure。
- 调用方只需构造 `AcquisitionRequest`；不得在调用方按 CNBC 年份/场次、YouTube URL、DOM 形态或页面选择器做分支。
- 站点特定的发现、解析、规范化与来源怪癖一律封装在对应爬虫内部。

## 爬虫契约与注册

- 每个站点实现 `application/ports.py` 的 `SourceCrawler` 协议，职责包括资源发现、抓取计划、页面解析、媒体引用提取、元数据规范化、溯源填充。
- 注册顺序：先注册来源特定爬虫（`CnbcCrawler`、`YoutubeCrawler` 等），`GenericCrawler` 兜底放最后。通用爬虫的 `accepts()` 会宽泛匹配，而 registry 会选中第一个接受的爬虫。
- `CnbcCrawler` 接受 CNBC URL、`cnbc:<year>` 或 `hints.year`；把年份展开为场次目标，并沿用遗留规则：存在完整上午/下午场时跳过 `highlight`。
- `YoutubeCrawler` 接受 YouTube URL 并返回 embed 媒体引用；除非真正能抓到逐字稿，否则不得声称提供 transcript。
- `GenericCrawler` 是选择器驱动的 HTML 页面兜底。
- 工件写入必须使用 `archive_core.application.build_asset_workspace()` 解析工作区，不得自创路径。

## 工件契约

对每个采集结果，writer 存储：

- `meta.json`：规范化后的来源元数据、`asset_id`、`source_ref`、`provenance`。
- `media_ref.json`：序列化的 `MediaReference`。
- `transcript.txt` 与 `chapters.json`：仅当 transcript 可用时写入。

写入必须按文件原子化；`overwrite=False` 时必须预检所有计划产出。

## 测试方向

- 单元测试覆盖：domain 校验、registry 路由、用例编排、writer 文件契约。
- 离线集成测试使用保存的 HTML fixture 与假 HTTP 客户端；不得触网，不得写出 `tmp_path`。
- 真实网络测试必须标记 `@pytest.mark.live`，默认跳过。
