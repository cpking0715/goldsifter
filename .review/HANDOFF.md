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

## findings 台账

（审阅后回填：fixed / rejected(理由) / open）
