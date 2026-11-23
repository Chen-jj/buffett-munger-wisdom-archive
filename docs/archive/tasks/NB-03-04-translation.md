# NB-03/04 分批初译、有界修订与唯一最终稿

> 2026-11-17归档说明：初版翻译/修订迁移技术交付归档；机械修订已被NB-09有界编辑生成替代，原过程与限制不删除。 原路径`docs/tasks/NB-03-04-translation.md`；原状态、历史不commit/push约束及验证结果属于当时记录。后续入口：[NB-12](NB-12-chunking-quality-iteration.md) / [ADR-0013](../decisions/0013-typed-chunking-quality-and-regression.md)。

状态：NB-03/04与翻译侧NB-07开发交付，待负责人完整真实验收；2026-11-06（Asia/Shanghai）。依赖 NB-01 公共契约与 NB-02 候选块。

## NB-03（ADR-0011）

替换旧句级用例/DTO/prompt/schema；保留provider显式配置与真实adapter，无自动fallback。
连带完整句组按section顺序组批，常规≤50chunks；超50完整句组单发，不截断。
只读上下文：有section为完整section+原标题；无section为批首前3句/批末后2句。
术语仅匹配本批正文，忽略大小写、词边界；辅助标记独立；预算原样传递不强制达标。
仅非空原标题的section首批翻标题。逐chunk严格有序ID/非空中文，拒绝未知/额外/乱序等。
每批checkpoint绑定实际请求/prompt/schema/术语/provider与source/chunks hash。预算超标不重试。
完整才manifest-last发布，不静默覆盖；复用仍验证。针对性测试后由负责人复跑。

## NB-04（ADR-0012）

独立用例：输入验证→只读试算→短gap机械合并→完整句组窗口有界修订→统一落定end→最终扫描。
借时仅需要min834ms与中文9CPS，不为英文CPS；≤500ms/总7s/媒体尾/下一词两帧边界，不移动词时间。
使用实际帧时间戳，缺证据不借该gap，只warning；实际重叠/越界/词覆盖或来源链错误阻断。
触发仅按ADR0012：中文CPS未解、英文>42或基本>7s、短gap合并失败；仅英文CPS/长度16/超短不新增模型调用。
窗口完整句组闭包，短gap取当前右块及前后块所涉完整句，合并重叠窗；固定边界中文精简失败才开放重切，格式错不放权。
模型只返状态/词范围/中文；程序重建英文和锚点，拒绝破保护跨度/边界/覆盖或引入新问题。
每稳定窗口最多3次内容请求，调用前持久记额度，失败/中断恢复不重置。未获合格候选保留前有效稿+warning。
最终稿绑定source/chunks/初译/媒体/政策；SRT/render均只消费它，不再做中文字符切片或比例。

## 交付与验证

NB-03先定向验收后NB-04，不一次隐藏完成。测试覆盖所有ADR边界、无解warning正式发布、持久额度/复用零调用；默认无网络/模型/进程。
真实生产composition可提供初译及修订两个public factory，编排不能直接调用私有实现。
同步模块/ADR真实状态；所有需删除的旧文件先报清单确认，能直接改写则不保留旧解析/生产分支。


## NB-03 开发记录（2026-11-05）

- 原workflow直接改写；新公开入口 `translation.interfaces.build_translation_handler`，command新增必需chunking manifest。
- StageManifest.stage采用core统一值`translation`，outputs只有`translation_result`。
- 新增纯规划/响应12项与编排目录真实local workflow集成9项：21 passed（0.46s）。
- 命令：`.venv/bin/python -m pytest tests/translation/test_chunk_translation.py tests/orchestration/integration/offline/translation/test_chunk_workflow.py -q`。
- 旧句级测试待NB-07契约替换，尚未完整离线通过；不声称完成真实provider、后处理或字幕质量验收。


## 2026-11-06 开发交付与边界

- NB-04 提供公开 `BilingualPostprocessingCommand` / `build_bilingual_postprocessing_handler()`，机械
  试算、短 gap 合并、句组闭包、有限修订、统一最终时间和告警正式发布。输出 keys 固定
  `final_bilingual_draft` / `report`，并以成功 `bilingual_postprocessing_manifest.json` 最后发布。
- 实际 decoded PTS 始终进入媒体来源证据；修订请求只发送窗内需要的时间与预算摘要，不发送全片帧表。
  额度先写后调，恢复按确定性请求与实际响应重算权限、接纳及理由。复测了格式拒绝→提供方失败→仅余
  一次、已接纳后发布失败→零模型重放、篡改放权/接纳与不信任旧成功 manifest。真实输出身份在负责人
  启动完整集成后冻结，本次不主动重跑昂贵阶段。
- 旧 `TranslationResultDTO`、`TranslationManifestDTO` 和句级解析/导出已直接移除定义；现有标题值
  只接受非空翻译。旧格式只能被拒绝；原有效断言映射至现行 DTO、阶段校验和发布行为。
- 原真实 Codex provider 用例已移到统一门控的 `provider_contract`，仍验证独立四句/两 section 与
  `go [editorial_break] ahead`，显式合成输入不是生产媒体链。合成夹具已本地解析/复验，未额外真实调用。
- 实际定向：`.venv/bin/python -m pytest tests/archive_core/test_translation_contracts.py tests/translation tests/orchestration/integration/{offline,live}/translation -q`
  → **276 passed / 1 skipped（0.97s）**。共享树阶段性全套：**2260 passed / 7 skipped（11.65s）**，
  此结果早于新增4项对抗回归和其他并行迁移收尾，不作为最终完整套件数字。
- 翻译和旧公共契约共207条开工 nodeid 已逐项映射至实际收集目标（54迁移、75替换、78保留）。
  不将离线绿、预算检查或结构覆盖当作语义、音画或出版质量通过。
