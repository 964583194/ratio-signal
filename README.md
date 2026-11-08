# 创业板50 ÷ 红利低波100 轮动信号

一个静态网页，两个页签：

- **比值轮动**：创业板50（399673）÷ 红利低波100（930955）的比值、所在区间、历史走势和每周定投回测。
- **红利打分**：红利低波100 每日定投打分（0~20 分，估值 15% / 技术 50% / 利差 25% / 风格 10%），八档金额、评分走势和每天 200 元的回测。
GitHub Actions 每个交易日自动拉取收盘价并更新数据，网页通过 GitHub Pages 免费托管。

## 文件说明

| 文件 | 作用 |
|---|---|
| `index.html` | 网页本体，读取 `data/ratio.json` 显示 |
| `scripts/update.py` | 拉取两个指数日线，计算比值、统计和回测，写入 `data/ratio.json` |
| `.github/workflows/update.yml` | 定时任务：工作日 17:30、周六 09:00（北京时间）自动运行 |
| `scripts/dividend.py` | 红利低波100 打分：PE、全收益指数推算股息率、十年国债、RSI/布林，写入 `data/dividend.json` |
| `data/ratio.json`、`data/dividend.json` | 数据文件，Actions 自动生成 |

## 部署步骤

1. 在 GitHub 新建一个仓库（公开仓库才能免费用 Pages），把本文件夹里的所有文件上传，保持目录结构不变。
   - 网页上传时注意 `.github` 是隐藏文件夹，建议用 GitHub Desktop 或 `git push` 上传，确保它被包含。
2. 打开仓库 **Settings → Actions → General**，在 Workflow permissions 选 **Read and write permissions**，保存。
3. 打开 **Actions** 页，选“更新比值数据”，点 **Run workflow** 手动跑一次，生成 `data/ratio.json`。
4. 打开 **Settings → Pages**，Source 选 **Deploy from a branch**，分支选 `main`、目录选 `/ (root)`，保存。
5. 一两分钟后访问 `https://你的用户名.github.io/仓库名/` 即可。之后每个交易日会自动更新。

## 数据来源与备用接口

每项数据都配了 3~5 个接口，按顺序尝试，第一个通过检查的就用；拿到的新数据会和本地缓存（`data/raw/`）比对，数值对不上的接口会被跳过，防止换了口径的数据混进来。所有接口都失败时，用缓存继续计算。

| 数据 | 接口（按优先顺序） |
|---|---|
| 创业板50 | 东方财富 → 国证指数官网 → 腾讯 → 新浪（近1000天） |
| 红利低波100 收盘 / 全收益 / 市盈率 | 中证指数官网 → 东方财富 → 中证指数官网（近两年） |
| 科创50 | 东方财富 → 中证指数官网 → 腾讯 → 新浪 |
| 中证A500 | 东方财富 → 中证指数官网 → 新浪 → 腾讯 |
| 沪深300 / A500 市盈率 | 中证指数官网（全量 → 近两年） |
| 中国十年国债 | 东方财富（+ 缓存） |
| 美国十年国债 | 东方财富 → 美国财政部 → 美联储 FRED |
| 纳指100 | 腾讯 → 新浪 → 东方财富 → 纳斯达克官网 → 美联储 FRED |
| 纳指ETF 513100 价格 / 净值 | 东方财富 / 天天基金 → 腾讯 / 东方财富 → 新浪 |

每次运行会写 `data/health.json`，页面底部显示状态。任何一项超过 12 天没更新，Actions 任务会失败，GitHub 自动发邮件提醒。
手动体检所有接口：`cd scripts && python sources.py`

## 旧版说明：数据来源

- 创业板50：东方财富日K接口
- 红利低波100：中证指数官网（失败时改用东方财富）

GitHub 的服务器在海外，偶尔会被这些接口拒绝。如果 Actions 运行失败，可以：

- 过一会儿在 Actions 页手动重跑；
- 或者在自己电脑上运行（国内网络更稳定），再把生成的 `data/ratio.json` 推到仓库：

```bash
python scripts/update.py
```

也可以用自己导出的数据（两列 CSV：日期,收盘价）：

```bash
CYB_CSV=创业板50.csv HL_CSV=红利低波100.csv python scripts/update.py
```

## 参数

在 `scripts/update.py` 顶部修改：

- `LO` / `HI`：低区线 0.16、高区线 0.28
- `WEEKLY`：每周定投额，默认 1000 元
- `FEE`：买入费率 0.05%
- `CASH_YIELD`：现金池年化 1.5%
- `DIV_CYB` / `DIV_HL`：股息率假设 0.6% / 5.0%（指数是价格指数，回测时按年化加回分红）

## 本地预览

直接双击 `index.html` 读不到数据文件，需要起一个本地服务：

```bash
python -m http.server
# 浏览器打开 http://localhost:8000
```

---

个人研究记录，不构成投资建议。
