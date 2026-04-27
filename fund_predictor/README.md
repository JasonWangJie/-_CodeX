# 基金预测/回测系统（fund_predictor）

## 项目说明
本项目是一个轻量级 Python3 命令行基金研究工具，支持：

1. 基金历史净值抓取与增量更新；
2. 基于 R1/R2/HV/加速度的超跌反弹信号计算；
3. 网格搜索回测与参数评分；
4. Markdown/HTML/JSON/CSV 报告输出；
5. 本地持仓交易管理（买入、跟踪、卖出、部分卖出）；
6. 收益概览查询（已实现收益 + 未实现收益）；
7. 交互控制台菜单。

## 基金代码配置（JSON）
程序已支持从 JSON 自动读取基金池。默认路径见 `config.yaml`：

```yaml
runtime:
  funds_json: "data/meta/funds.json"
```

默认示例文件：`data/meta/funds.json`，支持两种格式：

```json
["009689", "005827"]
```

或：

```json
[
  {"fund_code": "009689", "fund_name": "某某基金"},
  {"fund_code": "005827", "fund_name": "某某基金"}
]
```

当你未通过 `--funds` 或 `--fund-file` 传参时，系统会自动使用该 JSON 基金池。

## 缓存模式（新增）
默认使用文件缓存（parquet/csv）。如需提升多基金批量分析复用效率，可切换为 SQLite 缓存：

```yaml
storage:
  backend: "sqlite"
  sqlite_path: "data/meta/nav_cache.db"
  use_memory_cache: true
```

## 快速开始
```bash
python main.py analyze
python main.py console
```

更多命令与交互流程请看：`docs/操作手册.md`。
开发与维护细节请看：`docs/技术手册.md`。
