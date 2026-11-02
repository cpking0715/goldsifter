# 千淘轻服务端

轻服务端 + 重客户端架构中的"轻"端：License 发放/激活校验、客户端更新检查、匿名行情快照回传收集。重的（爬虫/AI/存储）全部在客户端。

## 端点

| 端点 | 方法 | 说明 |
|---|---|---|
| `/health` | GET | 健康检查（免认证） |
| `/api/v1/admin/licenses` | POST | 发放 License key（需 `X-Admin-Token` 头） |
| `/api/v1/license/activate` | POST | 激活到设备 `{key, device_id}`，超设备数 403 |
| `/api/v1/license/verify` | POST | 校验 `{key, device_id}`，过期返回 `ok:false`（客户端走离线宽限） |
| `/api/v1/update/latest` | GET | 更新检查 `?channel=stable|beta`，读 `data/update.json` 可热改 |
| `/api/v1/telemetry/snapshots` | POST | 匿名行情回传（≤200 条/批，仅行情字段，禁止个人身份信息） |

## 部署信息（ubuntu-tx-51，2026-11-02 已上线）

- 代码：`/opt/qiantao-server/`（venv + systemd `qiantao-server`，监听 `127.0.0.1:8120`，MemoryMax=400M）
- 入口：Caddy 8790 站点下 `/qt/*` 路径（`tls internal` 自签证书，客户端需跳过证书校验）
  - `https://119.45.234.51:8790/qt/...`（当前可用）
  - `https://qiantao.qingmuxi.com:8790/qt/...`（**待 DNS 加 A 记录 → 119.45.234.51**）
- 数据：`/opt/qiantao-server/data/app.sqlite3`（SQLite WAL）
- 管理令牌：`QT_ADMIN_TOKEN` 存于 `/etc/systemd/system/qiantao-server.service`（查看：`sudo grep QT_ADMIN_TOKEN /etc/systemd/system/qiantao-server.service`）
- Caddy 改动有备份：`/etc/caddy/Caddyfile.bak-qiantao-20261102`

## 本地开发与测试

```bash
python -m pytest tests/unit/test_light_server.py -q
QT_DB_PATH=/tmp/qt.db QT_ADMIN_TOKEN=dev uvicorn server.app:app --port 8120
```

## 更新发布

改 `/opt/qiantao-server/data/update.json` 即热生效（无需重启）：

```json
{
  "version": "1.1.0",
  "url": "https://.../qiantao-1.1.0.exe",
  "notes": "修复与优化",
  "mandatory": false,
  "channels": { "beta": { "version": "1.2.0-beta1", "url": "..." } }
}
```

## 运维

```bash
sudo systemctl status qiantao-server   # 状态
sudo journalctl -u qiantao-server -f   # 日志
sudo systemctl restart qiantao-server  # 重启
```
