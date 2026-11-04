# 千淘 · Qiantao

![千淘](docs/logo.png)

> 吹尽狂沙始到金 —— AI 帮你从二手市场的沙海里淘出真金。

多平台二手 AI 捡漏雷达：自然语言描述你要什么，系统持续监控闲鱼 / 孔夫子等平台的新上架商品，多模态 AI 看图判断成色与风险，命中好货秒推手机。

## 核心特性

- **AI 看图识货**：多模态模型分析商品图片、描述与卖家画像，输出推荐结论与风险标签（成色/真假/卖家信誉）
- **自然语言建任务**：一句话描述需求（"收一台 95 新 M1 MacBook，预算 5000 内"），AI 自动生成分析标准
- **多平台采集**：闲鱼（Playwright 反爬）/ 孔夫子旧书网（免登录）+ 插件化架构持续扩展
- **多模型供应商**：内置智谱（免费 Vision 模型）/ DeepSeek / 硅基流动 / 魔搭 / 百炼等预设，填 Key 即用，支持自定义 OpenAI 兼容接口
- **即时推送**：Bark / 微信 PushPlus / Telegram / 企业微信 / ntfy / Gotify / Webhook 七渠道
- **行情数据**：价格快照、市场均价、单品价格曲线，命中历史低位才推荐
- **账号与代理轮换**：多账号池、失败熔断、自动恢复
- **多种部署形态**：Docker / 源码 / Windows 客户端（托盘常驻，数据全在本地）

## 快速开始

### Windows 客户端（最简单）

1. 下载 `Qiantao-portable.zip`，解压
2. 双击「启动千淘.bat」→ 浏览器自动打开管理台
3. 按 Dashboard 首启引导三步走：改密码 → 配 AI（推荐智谱 `glm-4v-flash` 免费）→ 配推送

### Docker

```bash
cp .env.example .env   # 填入 OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL_NAME
docker compose up -d   # 打开 http://127.0.0.1:8000（默认 admin/admin123，请立即修改）
```

### 源码

```bash
pip install -r requirements.txt && playwright install chromium
cd web-ui && npm install && npm run build && cd ..
python desktop_tray.py        # 托盘模式；或 python -m src.app
```

AI 模型配置详见 [docs/AI-SETUP.md](docs/AI-SETUP.md)；架构与路线图见 [docs/DEV-SPEC.md](docs/DEV-SPEC.md)。

## 平台支持

| 平台 | 登录态 | 说明 |
|---|---|---|
| 闲鱼 | 需要（Chrome 扩展一键导出） | 反爬对抗完善，支持区域/包邮/个人闲置筛选 |
| 孔夫子旧书网 | 免登录 | 古籍/旧书，品相/书店信誉 AI 判断 |
| 悠悠有品 | 免登录 | CS2 游戏饰品，磨损值/Steam 参考价 AI 判断（Pro） |
| eBay | 免登录 | 海外中古好物，需海外网络环境（Pro） |
| 更多平台 | — | Collector 插件化架构，按 `src/collectors/` 模式扩展 |

## 授权（License）

免费版：2 个任务 + 闲鱼平台。Pro：全平台、无限任务。设置 → 云服务 → 输入授权码激活；离线 14 天宽限。

## 安全提示

- 首次登录后请**立即修改默认账密**（设置 → 系统状态 → 账号与安全）
- 建议限制访问来源或加 HTTPS 反代后再暴露公网；若经反向代理暴露公网，注意
  WebSocket 鉴权 token 走 URL 查询参数，会出现在代理访问日志中，建议收紧日志权限
- 请遵守目标平台用户协议，合理设置监控频率

## Credits

- 本项目基于开源项目 [ai-goofish-monitor](https://github.com/Usagi-org/ai-goofish-monitor)（MIT License）演进，感谢上游社区
- UI: Vue 3 + Tailwind + shadcn-vue；AI: 任意 OpenAI 兼容多模态模型

## License

MIT
