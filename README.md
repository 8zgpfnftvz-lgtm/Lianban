# 连板统计 PWA（扁平版，适合手机上上传）

所有文件都在根目录，不需要建 `icons` 文件夹。手机 GitHub 网页上传时，直接多选这些文件即可。

## 文件
`index.html`、`manifest.json`、`manifest.webmanifest`、`sw.js`、`icon-32.png`、`icon-180.png`、`icon-192.png`、`icon-512.png`、`icon-maskable-512.png`、`README.md`

## 部署
1. 手机浏览器打开仓库的上传页：`https://github.com/<用户名>/<仓库名>/upload/main`
2. 点「choose your files」，把上面这些文件全部选中（可多选）；
3. Commit changes；
4. 打开 `https://github.com/<用户名>/<仓库名>/settings/pages`；
5. Source 选 Deploy from a branch，Branch 选 main，目录 /(root)，Save；
6. 等 1~2 分钟，访问 `https://<用户名>.github.io/<仓库名>/`。

## 手机安装
- 安卓 Chrome：菜单 →「安装应用」/「添加到主屏幕」；
- iPhone Safari：分享 →「添加到主屏幕」。
