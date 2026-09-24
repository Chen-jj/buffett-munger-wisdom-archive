# 技术任务：media_download 跳过下载前验证已有工件

- 任务 ID：`MD-01`
- 优先级：`P0`
- 影响模块：`media_download`
- 依赖：无
- 被依赖：`TR-02` 的真实输入集成、`TR-06` 的端到端 transcription 验收
- 对应决策：[ADR-0001](../decisions/0001-transcription-sentence-level-alignment.md) §4、§13
- 状态：待实现

## 背景

当前 `DownloadAssetVideoService.plan()` 在发现目标 `video.mp4` 已存在且
`overwrite=False` 时，直接生成 `SKIP` 计划。这个判断没有先验证：

- `download_manifest.json` 是否存在且可以解析；
- manifest 是否属于当前资产和下载输入；
- manifest 是否记录成功的下载状态；
- manifest 中的文件路径、大小和 SHA-256 是否与实际 `video.mp4` 一致。

因此，一个残缺、被修改或来源不明的 `video.mp4` 也可能被当作已完成下载。这与
`media_download` 的约束冲突：阶段完成必须由 manifest 和 provenance 驱动，不能只依赖
文件存在。

## 目标

只有在已有视频及其下载 manifest 完整、匹配且校验通过时，下载计划才可以返回
`SKIP`。无法验证的已有视频必须产生明确的冲突或失败结果，且不得被自动删除、覆盖或
替换。

## 保留策略

- 管线禁止自动删除已下载的 `video.mp4`。
- 默认 `overwrite=False`，不得静默替换已有视频。
- 只有用户显式授权替换时才允许重新下载并覆盖；该授权必须通过明确的执行策略表达。
- 校验失败本身不构成删除或覆盖授权。

## 目标行为

| `video.mp4` | `download_manifest.json` | 校验结果 | 目标行为 |
|---|---|---|---|
| 不存在 | 不存在 | 不适用 | 正常规划下载 |
| 不存在 | 存在 | manifest 残留 | 不得判定完成；正常规划下载并在成功后更新廉价 manifest |
| 存在 | 不存在 | 无法验证 | 明确失败/冲突；不得删除或覆盖视频 |
| 存在 | 存在 | 解析、身份、状态或 checksum 失败 | 明确失败/冲突；不得删除或覆盖视频 |
| 存在 | 存在 | 全部通过 | 规划 `SKIP` 并返回已验证的下载工件 |
| 存在 | 存在或不存在 | 用户显式授权替换 | 规划重新下载；成功后更新视频和 manifest |

具体错误类型或计划状态可以在实现时按现有领域模型做最小扩展，但不能用模糊的
`SKIP` 隐藏校验失败。

## 校验要求

已有下载至少需要验证：

1. manifest schema 可识别并能完整反序列化；
2. manifest 的资产标识与当前 `DownloadInput.asset_id` 完全一致；
3. manifest 的媒体引用与当前输入一致；
4. 下载状态为成功；
5. manifest 工件路径指向当前资产的 canonical `video.mp4`；
6. 实际文件大小与 manifest 一致；
7. 实际文件 SHA-256 与 manifest 一致。

任何失败都必须可诊断，至少指出失败类别；错误信息不得包含敏感凭据。

## 实现范围

- 调整 `media_download` 的下载计划或执行前验证流程；
- 必要时对领域状态或错误类型做最小扩展；
- 补充离线测试；
- 若实现改变模块公开契约或已记录状态，同步更新相应文档。

## 非目标

- 不改变 yt-dlp 的格式选择策略；
- 不实现媒体内容质量检测；
- 不删除、移动或自动修复已有媒体文件；
- 不修改 transcription 或其他下游模块；
- 不建立通用清理器或资产生命周期框架。

## 验收标准

- 只有文件与 manifest 全部验证通过时才返回 `SKIP`；
- 文件存在但 manifest 缺失、损坏或不匹配时，操作明确失败且文件保持不变；
- checksum 或大小不匹配时，操作明确失败且文件保持不变；
- manifest 属于不同资产或媒体引用时，操作明确失败且文件保持不变；
- 视频不存在时仍能正常规划和执行下载；
- 用户显式授权替换时可以重新下载；未授权时绝不覆盖；
- fake downloader、artifact store 和 checksum adapter 下的离线测试覆盖上述分支；
- `python -m pytest tests/ -q -m "not live"` 全部通过。
