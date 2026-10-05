# 个人交易系统工作台（Python + AkShare）

依据《个人交易系统手册 V1.0》实现的本地产物：**先看大盘，再谈主线，最后才是个股与仓位**。

## 快速开始

```bash
# 1. 安装依赖（Python 3.10+）
python -m pip install -r requirements.txt

# 2. 启动应用
python -m streamlit run main.py
# 浏览器自动打开 http://localhost:8501
```

启动后在侧边栏选择模块。也可直接运行数据接口冒烟测试确认网络可用性：

```bash
python tools/smoke_test.py
```

## 六大模块

| 模块 | 功能 |
|---|---|
| 1 大盘数据 | 主要指数实时行情、涨跌家数、近似涨停、两市成交额、大盘阶段判断（强势/震荡/弱势/冰点）+ 对应仓位 |
| 2 主线行情个股分析 | 行业板块强度排行（涨幅+涨停家数+上涨占比+容量），强主线识别，新主线三特征说明 |
| 3 行业主线选股对比 | 选行业板块 → 成分股四维打分（动量/右侧/十日线战法/超跌），2-4 只 K 线 + MA + 布林带对比 |
| 4 交易系统决策 | 六大模型匹配（短线/波段/中线/长线/超跌反弹/右侧），命中条件清单、买点/卖点/止损参考；仓位计算器（单笔亏损预算 → 整手股数）。支持从自选股池/复盘页一键跳转自动带入标的代码 |
| 5 每日复盘 | 按手册字段录入（模型/依据/仓位/卖因/盈亏/情绪/教训），胜率与模型/情绪统计，CSV 导出；历史记录可一键跳转决策页再分析 |
| 6 自选股池 | 自选股增删（自动补名称、自动去重），实时行情表，选中标的 K 线速览（BOLL），一键跳转决策页分析 |

## 数据源与降级策略（重要）

应用以 **AkShare** 为首选数据源，但你当前的网络环境无法访问东方财富 push2 系列域名
（`push2.eastmoney.com` / `push2his` / `push2ex` 均被连接断开），因此数据层已内置
**自动降级通道**，页面与分析逻辑无需感知：

| 数据 | AkShare 首选 | 自动降级 |
|---|---|---|
| 指数实时 | stock_zh_index_spot_em（东财） | 新浪 hq.sinajs.cn |
| 指数日线 | stock_zh_index_daily（新浪） | -（本身即新浪） |
| 个股历史日线 | stock_zh_a_hist（东财，用户指定接口） | 新浪 getKLineData |
| 全市场快照 | stock_zh_a_spot_em（东财） | 新浪 Market_Center 并发分页（5571 只） |
| 行业板块行情 | stock_board_industry_spot_em（东财） | 腾讯 getRank |
| 板块成分股 | stock_board_industry_cons_em（东财） | 腾讯 getBoardRankList |
| 涨停池 | stock_zt_pool_em（东财） | 全市场快照近似（涨幅 ≥9.8%） |

降级带来的口径差异（已在页面标注）：
- **涨停家数**为近似值（涨幅 ≥9.8%），非真实涨停板池；**连板高度**在降级通道下不可得，主线评分中该维度并入容量分。
- **量比 / 60日涨跌幅 / 年初至今**列在降级通道下为空，个股技术指标以本地 K 线计算为准（MA/RSI/回撤/量比均自算）。
- 休市日（如国庆假期）涨停池为空、指数为最近交易日数据，属正常现象。

如果换到东财域名可达的网络，AkShare 首选源会自动生效，无需改代码。

## 配置与调参

所有可调参数集中在 `config.py`：
- `INDEX_WATCHLIST` 指数清单、`DEFAULT_INDEXES` 默认展示
- `MODELS` 六大模型规则（触发/买点/卖点/止损/仓位）
- `POSITION_TIERS` 五档仓位、`DEFAULT_RISK_RATIO` 单笔亏损预算
- `MARKET_PHASE_RULES` 大盘阶段划分、`SOP_TIMELINE` / `IRON_RULES` 纪律内容

## 项目结构

```
trading-system-py/
├── main.py                  # Streamlit 入口
├── pages/                   # 六个功能页面
│   ├── 1_大盘数据.py
│   ├── 2_主线行情个股分析.py
│   ├── 3_行业主线选股对比.py
│   ├── 4_交易系统决策.py
│   ├── 5_每日复盘.py
│   └── 6_自选股池.py
├── config.py                # 全部可调参数
├── data/market_data.py      # 多源数据层（AkShare + 新浪/腾讯降级）
├── analysis/
│   ├── market.py            # 大盘研判
│   ├── mainline.py          # 主线识别
│   ├── stock.py             # 选股打分与指标
│   ├── decision.py          # 模型匹配 + 仓位计算
│   ├── watchlist.py         # 自选股池存储
│   └── review.py            # 复盘存储与统计
├── data/reviews.json        # 复盘记录（运行时生成）
├── data/watchlist.json      # 自选股池（运行时生成）
└── tools/smoke_test.py      # 数据接口冒烟测试
```

## 边界说明

- 数据仅在当前浏览器会话本地使用，复盘记录保存在 `data/reviews.json`，换机器不共享。
- 所有指标均为简化启发式规则，用于个人决策参考与复盘，**不构成投资建议**。
