# archive_core AGENTS.md

## 模块定位

`archive_core` 持有全仓库共享的领域原语与契约，是其他所有模块都可以安全依赖的基础。

## 职责

- 存放各模块都能安全共享的基础领域模型：资产身份、工件与命名契约、工作区路径策略、管线状态、溯源等横切领域概念。
- 判据：与具体站点、外部工具无关且被多个模块需要 → 放这里；只属于单个管线阶段的业务概念 → 放对应功能模块。
- 本模块的规则必须保持纯：不依赖 HTTP、ffmpeg、OpenAI 兼容 API 或 Web UI。

## 分层规则

- `domain/`：值对象、实体、校验策略、命名规则、工件状态流转。
- `application/`：仅当用例真正跨模块时才放这里，如解析资产工作区、校验工件 manifest。
- `infrastructure/`：读写核心 manifest 的最小共享适配器（仅当不属于某个具体功能模块时）。
- `interfaces/`：供 CLI、Web UI、review、orchestration 使用的 DTO 与序列化器。

## 技术方向

- 领域概念优先用 dataclass 或小型类型化对象。
- 序列化保持显式且有版本号；避免跨模块裸传 dict。
- 本模块避免重依赖。
