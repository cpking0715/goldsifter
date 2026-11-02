# DEV-SPEC：多平台二手 AI 捡漏雷达（第一阶段）

> 组合路线 1→3 的第一阶段规格。上游：ai-goofish-monitor（MIT，柔性 fork，保持可 merge）。

## 产品命名（待用户最终确认）

- **产品名：千淘** —— 出自刘禹锡《浪淘沙》"千淘万漉虽辛苦，吹尽狂沙始到金"；副标：AI 帮你从二手沙海里淘出真金
- **仓库名：`goldsifter`**（英文叙事名）；英文副名 Qiantao — *Sift gold from the sands of second-hand markets*
- 备选已否决：淘汐（意象偏行情、对回收商抽象）、慧眼识货（与虎扑「识货」商标重叠）
- 命名约束：不带闲鱼/Goofish 字样（平台中性 + 产品独立性）；不锁死"捡漏"定位（兼容行情数据阶段）
- 全量 rebrand（应用标题/前端页面/README/仓库改名）属对外动作，待用户明确口令后一次性执行

## 一句话产品

在现有闲鱼 AI 监控基础上，抽象出平台无关的采集层（Collector），新增孔夫子旧书网作为第二平台，验证"采集 → AI 判断 → 通知"管道的多平台化架构，为后续转转/eBay 接入与行情数据产品蓄能。

## 做什么

- **Collector 插件化架构**：`src/collectors/` 新包，`Collector` 协议 + 平台注册表；闲鱼采集以薄包装接入（`src/scraper.py` 本体不动，保持上游可 merge）。
- **孔夫子 collector（MVP）**：httpx 抓取服务端渲染的搜索页，产出与闲鱼一致的商品契约；支持价格区间/翻页；无需登录态。
- **平台能力声明**：每个 collector 声明支持的筛选条件（孔夫子不支持"个人闲置/包邮/区域/新发布"），任务表单按能力动态显隐。
- **任务级 `platform` 字段**：Task 模型 + SQLite 迁移，默认 `xianyu`，旧数据零影响。
- **商品契约显式化**：`src/collectors/contract.py` 定义商品记录必备字段与校验函数，所有 collector 输出必须通过校验。
- **结果与行情数据平台隔离**：非闲鱼平台的结果文件名与价格快照 slug 加平台前缀，避免同关键词跨平台混写；闲鱼保持原命名（向后兼容）。
- **真鉴权**：登录签发 HMAC 签名 token，保护全部 `/api/*` 与 `/ws`；`/health` 免认证。
- **前端**：任务表单平台选择器 + 按能力显隐筛选项；结果卡片显示来源平台徽标；请求携带 token。

## 不做什么（本阶段边界）

- 不做转转 / eBay / Facebook Marketplace collector（Phase 2）。
- 不做多用户 / 租户体系 / 用户表（单用户 token 加固；SaaS 化后置）。
- 不做跨平台同款比价、行情聚合页面与保值率榜单（Phase 3，依赖 price_snapshots 数据积累）。
- 不做孔夫子卖家深度画像采集（seller_loader 传空实现，接口已支持）。
- 不做产品改名 / rebrand（对外动作，发布前单独拍板；用户可见文案不提移植痕迹）。
- 不改闲鱼采集本体 `src/scraper.py` 的内部逻辑（只允许包装调用与极小侵入点）。

## 范围边界

| 模块 | 改动 | 说明 |
|---|---|---|
| `src/collectors/`（新） | 新增 | base / contract / registry / xianyu / kongfz |
| `spider_v2.py` | 小改 | 按 task.platform 从注册表分发 |
| `src/domain/models/task.py` | 追加字段 | `platform`，默认 xianyu |
| `src/infrastructure/persistence/` | 追加列 | tasks.platform 迁移；storage_names 支持平台前缀 |
| `src/services/price_history_service.py` | 小改 | slug 支持平台命名空间（xianyu 不前缀） |
| `src/services/result_storage_service.py` | 小改 | 保存/去重加载支持 platform |
| `src/api/`（新 + app.py） | 鉴权 | token 依赖项挂到全部路由；/ws 校验 query token |
| `src/infrastructure/config/settings.py` | 追加 | `WEB_AUTH_SECRET`（可选，缺省从账密派生） |
| `web-ui/` | 小改 | http 层带 token、WS 带 token、任务表单平台选择、结果徽标 |
| `tests/` | 新增 | test_auth / test_tasks_platform / test_collectors_contract |

## 验收口径

1. `pytest` 全量通过（含新增测试），前端 `npm run build` 通过。
2. 旧库升级：带历史任务的 SQLite 启动后自动补 `platform='xianyu'`，闲鱼任务行为与升级前一致（回归）。
3. 契约测试：闲鱼 fixture 与孔夫子 fixture 解析结果均通过 `validate_item_record`。
4. 鉴权：未带 token 访问任一 `/api/*` 返回 401；`/ws` 无 token 被拒；登录后带 token 全部放行。
5. 冒烟：创建孔夫子关键词任务 → 启动 → 商品落库、结果页可查（带平台徽标）、测试通知渠道可收到推送。
6. 同关键词双平台任务结果互不污染（结果文件与价格快照分开）。

## 路线图

- **Phase 0（本轮）**：基建——鉴权、platform 字段、Collector 抽象、契约显式化。
- **Phase 1（本轮）**：孔夫子 collector MVP + 前端平台选择。
- **Phase 2（后续）**：转转 / eBay collector、跨平台同款比价、回收商专业版（多账号高频）。
- **Phase 3（后续）**：行情数据产品——品类指数 / 保值率榜 / 价格预警 / 数据 API（Keepa 模式）。

## 硬约束

- 柔性 fork：新增代码独立成包，闲鱼路径追加式改动，保持与上游可 merge。
- 保留 MIT 许可与上游版权声明。
- 商品契约向后兼容：中文键名不变（结果页 / 导出 / AI prompt / 通知均依赖）。
- 凭据不落源码；token 密钥走 `.env`（`WEB_AUTH_SECRET`）。
