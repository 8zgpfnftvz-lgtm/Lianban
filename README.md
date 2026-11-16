# 天天板 · 连板统计 PWA

这是天天板体系里的独立连板复盘页，保留连板统计、梯队日线、断板节点案例和开盘啦题材数据，并统一为天天板的品牌、卡片密度和手机交互。

连板统计下方新增按交易日联动的首板统计表，展示首板股票、题材、涨停原因、封板状态、涨幅、首封时间和开板次数。

断板案例采用“案例说明＋中位股断板表＋结构判断”的格式，并在每张案例底部提供对应交易日的打板客网公开复盘链接，方便核对日期、最高板和中位股表现。

所有文件都在根目录，不需要另建 `icons` 文件夹。手机 GitHub 网页上传时，直接多选以下文件：

`index.html`、`manifest.json`、`manifest.webmanifest`、`sw.js`、`dabanke_data.json`、`first_board_data.json`、`tools/fetch_dabanke.py`、`tools/fetch_first_boards.py`、`.github/workflows/update-dabanke.yml`、`icon-32.png`、`icon-180.png`、`icon-192.png`、`icon-512.png`、`icon-maskable-512.png`、`README.md`、`.nojekyll`

## 打板客数据更新

PWA 运行时读取同源的 `dabanke_data.json`。GitHub Actions 在 A 股交易日盘后运行：

1. 抓取最新交易日，以及最近5个案例断板日；
2. 只保存中位股涨跌幅、封板状态、最高板、封板率和市场摘要；
3. 自动提交更新后的 `dabanke_data.json`。

`tools/fetch_first_boards.py` 同时增量更新 `first_board_data.json`，保存各交易日首板股及涨停原因。

也可以在 GitHub 仓库的 Actions 页面手动运行 `Update Dabanke review data`。

## GitHub Pages 部署

1. 手机浏览器打开仓库的上传页：`https://github.com/8zgpfnftvz-lgtm/Lianban/upload/main`
2. 点「choose your files」，把上面这些文件全部选中（可多选）；
3. Commit changes；
4. 打开 `https://github.com/<用户名>/<仓库名>/settings/pages`；
5. Source 选 Deploy from a branch，Branch 选 main，目录 /(root)，Save；
6. 等 1~2 分钟，访问 `https://8zgpfnftvz-lgtm.github.io/Lianban/`。

## 手机安装

- 安卓 Chrome：菜单 →「安装应用」/「添加到主屏幕」；
- iPhone Safari：分享 →「添加到主屏幕」。

更新页面后需要刷新一次，让新的 Service Worker 接管；历史日线仍按原来的本机缓存逻辑保存。
