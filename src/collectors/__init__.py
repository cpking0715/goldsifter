"""
多平台采集层（Collector）。

包内模块保持轻量：platforms/contract/base 不引入 playwright/httpx 等重型依赖，
具体平台采集器（xianyu/kongfz）由 registry 懒加载，避免 API 进程承受无关依赖。
"""
