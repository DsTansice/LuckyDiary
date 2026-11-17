# 倒霉鬼的倒霉日记

这是“倒霉鬼的倒霉日记”网站项目：把倒霉鬼在奶昔论坛写下的帖子归档成个人日记，按论坛原始发帖时间展示。网站保留已归档文章，只增量添加新帖；生成的静态站点可部署到 Cloudflare Pages。

## GitHub Actions 登录配置

1. 在 GitHub 仓库打开 **Settings → Secrets and variables → Actions → New repository secret**。
2. Name 填 `FORUM_COOKIE`，Secret 填从浏览器开发者工具 Network 请求头复制的完整 `Cookie` 值。
3. 不要把 Cookie 提交到仓库、写入 workflow 文件或贴到聊天中。Cookie 等同于账号登录凭据；如已泄露，请退出论坛并重新登录以更新会话。
4. 打开 **Actions → Update forum diary → Run workflow** 手动同步。Workflow 将 Cookie 作为 `FORUM_COOKIE` 环境变量传给抓取脚本。

脚本会扫描个人帖子列表前 10 页，只抓取尚未存档的帖子。已有存档内容保持不变；若无法读取原帖的论坛时间，任务会报错而不是用抓取时间替代。

## 发布网站

将 Cloudflare Pages 连接到此 GitHub 仓库，构建输出目录设为 `dist`。Actions 有新归档时会提交 `data/posts.json` 和生成后的静态文件，Git 集成随后会触发重新部署。

评论区使用 Giscus。部署前在 `assets/index.html` 中把 `data-repo`、`data-repo-id`、`data-category` 和 `data-category-id` 替换为已启用 Discussions 的 GitHub 仓库对应值。
