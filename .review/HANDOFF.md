# Handoff — 千淘（goldsifter）二开第一阶段：多平台架构 + 鉴权 + 云服务

## 任务

在上游 ai-goofish-monitor（MIT，闲鱼单平台）基础上做"组合路线 1→3"第一阶段：
多平台采集架构（孔夫子接入）、token 鉴权、轻服务端（License/更新/行情回传）、
Windows 托盘启动器、智谱等低 max_tokens 服务商兼容。规格见 docs/DEV-SPEC.md。

## 已实现

1. **Collector 插件化**：`src/collectors/`（platforms 元数据/contract 商品契约/base+registry 懒加载/xianyu 薄包装/kongfz 采集器直连 JSON 接口）；Task 模型加 platform 字段 + SQLite 迁移；spider_v2 按平台分发；非闲鱼平台结果文件与价格快照 slug 加平台前缀（闲鱼历史命名不变）。
2. **token 鉴权**：`src/api/auth.py`（HMAC-SHA256 签名 token，无新依赖）保护全部 /api/*；WS 握手校验 query token；密钥 WEB_AUTH_SECRET 可配、缺省从账密派生。
3. **轻服务端** `server/app.py`（已部署 tx-51，systemd 8120 + Caddy /qt/*）：License 发放(admin token)/激活(设备上限)/校验、更新清单(data/update.json 热改)、匿名行情快照回传收集。
4. **客户端云服务** `src/services/cloud_service.py` + `/api/cloud/*` + Settings 云服务 tab：License 14 天离线宽限、回传水位推进与脱敏（仅行情字段）、更新检查、telemetry 后台循环（lifespan）。
5. **托盘启动器** `desktop_tray.py`（pystray 可选，退化前台）。
6. **AI 兼容**：max_tokens 超限识别/提取上限/自动降级（AIClient 与 ai_handler 两条路径）；OPENAI_TEXT_MODEL_NAME 双模型分工；ai_handler stdout detach 改 reconfigure（修 pytest 崩溃）。
7. 前端：任务表单平台选择器（能力显隐）、结果平台徽标、token 携带（http/ws/useAuth）、云服务 tab、favicon/标题。

## Diff 基线

base=77f8d75  head=af67c5e
审阅范围命令：git diff 77f8d75...af67c5e

## 改动文件

后端核心：src/collectors/*（新）、src/api/auth.py（新）、src/api/routes/{cloud,platforms}.py（新）、
src/api/routes/{tasks,results,websocket}.py、src/app.py、src/domain/models/task.py、
src/infrastructure/persistence/{sqlite_connection,sqlite_task_repository,sqlite_bootstrap,storage_names}.py、
src/infrastructure/config/settings.py、src/infrastructure/external/ai_client.py、
src/services/{price_history_service,result_storage_service,result_file_service,dashboard_payloads,task_generation_runner,cloud_service}.py、
src/{scraper,ai_handler,prompt_utils}.py、spider_v2.py、server/app.py（新）、desktop_tray.py（新）
前端：web-ui/src/{lib/http.ts,services/websocket.ts,composables/useAuth.ts,api/{cloud,platforms}.ts,lib/platform.ts(新),types/*,views/SettingsView.vue,components/tasks/TaskForm.vue,components/tasks/TasksTable.vue,components/results/ResultCard.vue,composables/useResults.ts,i18n/messages/*}、web-ui/index.html、web-ui/public/favicon.svg
测试：tests/unit/{test_light_server,test_cloud_service,test_auth,test_tasks_platform,test_collectors_contract}.py（新）、test_ai_request_compat.py、tests/fixtures/kongfz_item.json
其他：.env.example、.gitignore、docs/（DEV-SPEC.md、logo）

## 测试

- `python -m pytest -q` → 退出码 1（存在失败）：**153 passed, 6 failed, 3 skipped**。
  6 个失败（failure_guard×2、frontend_build_paths、ai_client sanitize_no_proxy×2、utils save_to_jsonl）
  经 pristine HEAD(77f8d75) worktree + 同款 stdout 修复对比，确认为上游既有失败，与本 diff 无关。
- `cd web-ui && npm run build` → 成功（✓ built in ~4s）。
- 真实冒烟（详见对话）：鉴权 401/token 200、孔夫子全链路（20 商品落库+AI 判定+通知+insights+去重）、
  WS 1008 拒绝/广播、闲鱼守卫、云服务闭环（激活/校验/回传落 tx-51/更新检查）均实测通过。

## 已知假设与未验证项

- 孔夫子接口逆向于 2026-11-02 验证，改版需更新解析（fixture 测试锁格式）。
- 轻服务端 tls internal 自签（客户端 verify=False），域名未备案，走 8790 非标端口。
- License 尚未做功能门禁（仅状态），Pro/free 分界待定。
- desktop_tray 在无桌面环境只验证了退化路径，托盘 UI 未自动化测试。
- 上游 6 个既有失败未修（范围外）。

## Review 焦点

1. **鉴权完整性**：/api/* 是否全部在 app.py 挂了 require_auth？/auth/status、/health、静态挂载、SPA catch-all 是否有未保护的敏感面？token 签名/校验（auth.py）有时序安全与降级问题吗？
2. **路径与注入**：results/prompts 路由的 filename 参数穿越防护；SQLite 全部参数化？（grep f-string SQL）
3. **隐私红线**：cloud_service.collect_pending_snapshots 的字段白名单是否可能泄漏 seller/link/region？水位推进与失败重传语义。
4. **轻服务端暴露面**（server/app.py，公网可达）：admin token 比对、telemetry 无限写入（缺 rate limit？）、SQLite 并发、license 并发激活竞态。
5. **平台数据隔离**：build_result_filename/parse_result_filename/normalize_keyword_slug 的前缀匹配是否可能串平台（如 keyword 本身含 "kongfz__"）。
6. **AI 双路径降级**（ai_handler.py / ai_client.py）：降级后 1024 截断分析 JSON 的容错；两条路径逻辑重复的偏差。
7. 子进程 spawn（process_service）命令构造是否有注入面；任务名进日志文件名的清洗。

## findings 台账（Cursor 12 条 + 自审计 5 条，2026-11-03）

| # | 来源 | 严重度 | 问题 | 状态 |
|---|------|--------|------|------|
| 1 | Cursor major | auth.py compare_digest 长度不等抛 ValueError→500 | **fixed**（先比长度） |
| 2 | Cursor major | 默认账密派生 HMAC 密钥可离线伪造 token | **rejected**：伪造材料=账密本身，与登录接口攻击门槛完全等效，无增益；建议改默认账密/配 WEB_AUTH_SECRET（文档已提示） |
| 3-5 | Cursor major×3 | kongfuz__ 前缀/slug 理论碰撞致跨平台串读误标 | **open**：需用户刻意以 kongfuz_ 前缀命名闲鱼关键词才触发，数据质量问题非安全漏洞；Phase 2 快照表加 platform 列彻底解决 |
| 6 | Cursor major | telemetry 无配额可灌爆磁盘 | **fixed**（每 IP 20/min 限流 + 全局日 20 万/总量 500 万配额，429） |
| 7 | Cursor major | License 激活 COUNT+INSERT 竞态 | **fixed**（BEGIN IMMEDIATE 写锁互斥） |
| 8 | Cursor major | verify=False 可 MITM | **fixed**（严格 CA pin：ca/qiantao-cloud-root.crt + SSLContext 不加载系统 CA + trust_env=False 直连；正反双向实测） |
| 9 | Cursor minor | admin token compare 长度异常→500 | **fixed** |
| 10 | Cursor minor | 登录 == 非恒定时间 | **fixed**（compare_digest） |
| 11 | Cursor minor | AI 双路径截断 JSON 容错不一致 | **open**：实际调用面为零（analyze 无调用方），双路径合并重构时处理 |
| 12 | Cursor minor | results 下载 200+error 不一致 | **rejected**：上游既有行为，柔性 fork 原则不动 |
| A | 自审计 medium | 轻服务端无速率限制 | **fixed**（IP 滑动窗口限流，tx-51 实测第 11 次 429） |
| B | 自审计 minor | WS token 走 query（反代日志可见） | **open**：本地部署影响小，公网部署需注意 |
| C | 自审计 minor | parse_result_filename 前缀误判 | **open**（同 #3 合并处理） |
| D | 自审计 info | 确认项 | SQL 参数化/无 v-html/spawn 无 shell/git 历史干净/.env 未跟踪/prompts 穿越防护 ✓ |

修复验证：pytest 155 通过/6 上游既有失败；tx-51 部署后限流/健康实测；客户端严格 pin 正反验证；
验收冒烟矩阵 12/12（孔夫子全链路/去重/insights/WS/闲鱼守卫/云闭环/license 重激活）。

---

# Handoff — 监控结果分类与过滤改造（分类 Tab / 搜索 / 价格区间 / 收藏 / 加载更多）

## 任务

闲鱼监控结果页原本是平铺卡片流：仅「仅AI推荐/仅关键词推荐/显示隐藏」三个勾选框，无搜索与价格/时间过滤，且前端写死 page=1 limit=100（超过 100 条的旧结果永远看不到）。要求做分类与过滤，让用户「先看重点、快速过滤、翻得完」。

## 已实现

- 分类 Tab（带数量角标）：全部 / AI 推荐 / 高性价比（value_score≥60）/ 关键词命中 / 收藏 / 已屏蔽，替代旧 3 勾选框
- 标题/卖家搜索（前端 300ms 防抖）、价格区间、发现时间（24h/3d/7d/30d/自上次查看，基于 crawl_time 字典序比较）
- 收藏：result_items 加 is_favorite 列（幂等迁移）+ PATCH favorite 端点 + 卡片★按钮（乐观更新）
- 加载更多：修复只能看前 100 条的问题，「已显示 X / 共 Y 条」
- 新商品：per-file localStorage 水位（上次查看的最新 crawl_time），卡片「新」角标 +「自上次查看」筛选项
- 任务进程结束后广播 results_updated（激活前端已有但后端从未发送的死监听）
- 卡片补渲染商品标签 chips（≤3 个）；CSV 导出同步支持全部新过滤参数
- 后端过滤改为「SQL 全量加载+装饰 → Python 过滤/分类计数/性价比排序 → 内存分页」，列表响应附带 counts

## Diff 基线

base=e30528e  head=<本次提交（见 git log -1）>
审阅范围命令：git diff e30528e...HEAD

## 改动文件

后端：
- src/infrastructure/persistence/sqlite_connection.py（is_favorite 列迁移+索引）
- src/services/result_storage_service.py（核心：装饰/过滤/计数/排序/收藏，query_result_records 返回三元组）
- src/api/routes/results.py（新参数 category/search/min_price/max_price/found_since；counts 响应；PATCH favorite；GET counts）
- src/app.py（任务停止时广播 results_updated）

前端：
- web-ui/src/composables/useResults.ts（重写：filters 新结构/防抖/加载更多/水位/收藏）
- web-ui/src/components/results/ResultsFilterBar.vue（重写：分类 Tab 行+过滤行）
- web-ui/src/components/results/ResultCard.vue（★收藏、新角标、商品标签）
- web-ui/src/components/results/ResultsGrid.vue（加载更多、事件透传）
- web-ui/src/views/ResultsView.vue、api/results.ts、types/result.d.ts、i18n zh-CN/en-US

测试：
- tests/integration/test_api_results.py（新增 5 个用例）
- tests/unit/test_tasks_platform.py（迁移幂等用例）

## 测试

- `python -m pytest -q` → **177 passed, 6 failed, 3 skipped**。6 个失败已在 HEAD 干净 worktree（e30528e）上验证为上游既有失败（failure_guard×2 / frontend_build_paths / ai_client×2 / test_save_to_jsonl），非本次回归。
- `cd web-ui && npm run build`（vue-tsc -b && vite build）→ 退出码 0。
- 浏览器冒烟（8100 端口 + 真实库临时副本）：Tab 计数 941/127/126/0/0/0 正确；AI 推荐 Tab 过滤正确；加载更多 100→127；收藏往返（★点亮+计数 0→1+收藏 Tab 过滤）；搜索「国行」941→674 全命中；价格 ≥6500 → 275 条且边界正确；屏蔽→已屏蔽 Tab→恢复全链路正常。

## 已知假设与未验证项

- found_since 用「本地 naive ISO 字符串字典序比较」：前端按同格式生成（toLocalIso），服务端不解析时区；前提是 crawl_time 全为 `datetime.now().isoformat()` 同源格式（当前代码如此）。
- 「新」角标与「自上次查看」在冒烟中未实机触发（需任务跑出新数据）；逻辑为纯前端水位推导，未实测。
- 高性价比阈值 60 为常量（HIGH_VALUE_SCORE_THRESHOLD），未配置化。
- value_score 仅 AI 输出该扩展时存在；缺失时该 Tab 计数为 0（符合设计）。
- 结果集按关键词划分（实测 941 条），全量加载+Python 过滤性能可接受；未对万级以上结果集压测。

## Review 焦点

1. `result_storage_service.py` 的 `_apply_record_filters`：category=hidden 与 include_hidden 旧参数的语义互斥是否符合预期（hidden 分类只显示被隐藏项）。
2. 旧 API 兼容：ai_recommended_only/keyword_recommended_only/include_hidden 旧参数路径是否有行为漂移（既有测试已覆盖，但请复核 normalize 逻辑）。
3. useResults.ts 水位推进（advanceNewSince）与「自上次查看」参数的时序：请求前快照 watermark、响应后推进，是否存在筛选组合下的边界问题。
4. routes 里 `ResultCategory` 枚举与 service 层常量字符串的一致性（两处定义）。
5. toggleItemFavorite 乐观更新失败回滚是否有竞态（连续快速点击）。

## findings 台账（本轮）

Cursor 审阅（2026-11-04，对 671bb80）：

| # | 来源 | 严重度 | 问题 | 状态 |
|---|------|--------|------|------|
| 1 | Cursor blocker | 「自上次查看」用已前移的 watermark 做 found_since，选中即清空列表 | **fixed**：改用 prevVisit 基线（上一次见到新数据前的水位）；首访 prevVisit=null 时筛选不生效（show all），不再首访即空 |
| 2 | Cursor major | category=hidden 分支 continue 过早，跳过搜索/价格/时间过滤 | **fixed**：hidden 分支只做可见性反转，其余条件统一 fall-through；补 3 条回归测试 |
| 3 | Cursor major | toggleItemFavorite 连点响应乱序致状态不一致 | **fixed**：per-item 在途 Set 串行化，在途时忽略重复点击 |
| 4 | Cursor minor | export 缺 min_price>max_price 校验，静默导出空 CSV | **fixed**：与列表接口同样返回 400；补回归测试 |

修复验证：`pytest tests/integration/test_api_results.py` → **11 passed**；`npm run build` → 退出码 0。
findings #1/#3 为前端逻辑（无前端测试基建），以 vue-tsc 类型检查 + 构建 + 代码走读验证。

第二轮复审（2026-11-04，对 74f067c）：台账 4 条确认完整落地，另出 3 条收藏成功路径残留：

| # | 来源 | 严重度 | 问题 | 状态 |
|---|------|--------|------|------|
| R2-1 | Cursor major | counts 刷新失败会误回滚已成功的收藏；快切文件可能把旧 counts 盖到新文件 | **fixed**：updateItemFavorite 与 counts 刷新分离，仅前者失败才回滚；counts 赋值前校验 selectedFile 未变 |
| R2-2 | Cursor major | 「收藏」Tab 下取消收藏后卡片残留 | **fixed**：取消收藏且当前分类为 favorite 时本地移除卡片并 total-1（避免整页刷新丢已加载分页） |
| R2-3 | Cursor minor | export 400 时前端只见 HTTP error，看不到后端 detail | **fixed**：downloadResultExport 解析响应 detail 透出（如「最低价不能高于最高价」） |

修复验证：`python -m pytest -q` → **179 passed, 6 failed（上游既有）**；`npm run build` → 退出码 0。

