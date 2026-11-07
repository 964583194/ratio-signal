# 创业板50 ÷ 红利低波100 轮动信号

一个静态网页，展示 创业板50（399673）÷ 红利低波100（930955）的比值、所在区间、历史走势和每周定投回测。
GitHub Actions 每个交易日自动拉取收盘价并更新数据，网页通过 GitHub Pages 免费托管。

## 文件说明

| 文件 | 作用 |
|---|---|
| `index.html` | 网页本体，读取 `data/ratio.json` 显示 |
| `scripts/update.py` | 拉取两个指数日线，计算比值、统计和回测，写入 `data/ratio.json` |
| `.github/workflows/update.yml` | 定时任务：工作日 17:30、周六 09:00（北京时间）自动运行 |
| `data/ratio.json` | 数据文件，首次运行 Actions 后自动生成 |

## 部署步骤

1. 在 GitHub 新建一个仓库（公开仓库才能免费用 Pages），把本文件夹里的所有文件上传，保持目录结构不变。
   - 网页上传时注意 `.github` 是隐藏文件夹，建议用 GitHub Desktop 或 `git push` 上传，确保它被包含。
2. 打开仓库 **Settings → Actions → General**，在 Workflow permissions 选 **Read and write permissions**，保存。
3. 打开 **Actions** 页，选“更新比值数据”，点 **Run workflow** 手动跑一次，生成 `data/ratio.json`。
4. 打开 **Settings → Pages**，Source 选 **Deploy from a branch**，分支选 `main`、目录选 `/ (root)`，保存。
5. 一两分钟后访问 `https://你的用户名.github.io/仓库名/` 即可。之后每个交易日会自动更新。

## 数据来源

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
