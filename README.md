# 倒霉鬼的倒霉日记

这是“倒霉鬼的倒霉日记”网站项目：把倒霉鬼在奶昔论坛写下的帖子归档成个人日记，按论坛原始发帖时间展示。网站保留已归档文章，只增量添加新帖；生成的静态站点可部署到 Cloudflare Pages。

## GitHub Actions 登录配置

1. 在 GitHub 仓库打开 **Settings → Secrets and variables → Actions → New repository secret**。
2. 添加 `FORUM_USERNAME` 和 `FORUM_PASSWORD` 两个 Secrets，分别填写论坛用户名和密码。如果账号登录需要安全问题，添加 `FORUM_QUESTION_ID`（登录表单中对应问题的 ID）和 `FORUM_ANSWER`。无安全问题时可以不设置这两个值，脚本会选表单默认的“无”。
3. 不要把用户名、密码、安全问题答案或 Cookie 提交到仓库或贴到聊天中。它们都是账号凭据。
4. 打开 **Actions → Update forum diary → Run workflow** 手动同步。Workflow 会将 Secrets 作为环境变量传给抓取步骤，先读取论坛动态登录表单，再执行登录。脚本只复用登录后的会话来抓帖子，不会执行 HAR 中的签到请求。
5. 也可以不配置账号密码，改为配置 `FORUM_COOKIE` Secret，作为登录 Cookie 的回退方式。

首次同步（存档为空）会按 `order=dateline` 扫描个人帖子列表前 10 页；首次成功后，后续增量同步只扫描第一页。列表页 `#threadlisttableid` 是 `<ul>`，每篇帖子是一项 `li.kmlist.common`，只从其中的 `a.kmtit` 读取帖子 URL 和标题，不扫描其它链接。正文和原始发布时间从帖子页 `#postlist` 的首帖提取。只抓取尚未存档的帖子；已有存档内容保持不变。若列表中的旧帖详情页返回 HTTP 404，会输出 warning 并跳过该帖，继续处理其它帖子；其它 HTTP 错误仍会让任务失败。列表和帖子页都无法读取原始时间时，任务会报错而不是用抓取时间替代。

## 发布网站

将 Cloudflare Pages 连接到此 GitHub 仓库，构建输出目录设为 `dist`。Actions 有新归档时会提交 `data/posts.json` 和生成后的静态文件，Git 集成随后会触发重新部署。

评论区使用 Giscus。部署前在 `assets/index.html` 中把 `data-repo`、`data-repo-id`、`data-category` 和 `data-category-id` 替换为已启用 Discussions 的 GitHub 仓库对应值。
