# 概念

## 文档（Document）

一篇文档由 `slug` 唯一标识，URL 是 `/d/<slug>`，永远不变。它有：

| 字段 | 说明 |
|---|---|
| `title` | 标题 |
| `category` | 目录式路径，如 `guides/onboarding`。分类不是预先定义的，发布时写什么就有什么 |
| `kind` | `md` 或 `html` |
| `tags`、`summary`、`status` | 标签、摘要（没给就从正文截取）、状态 `draft / review / approved / deprecated` |
| `created_by`、`created_at`、`updated_at` | 作者与时间（存 UTC，按 `DOCSTATE_TZ` 显示） |
| `latest_version` | 最新版本号 |
| `archived_at` | 归档时间；归档后不再出现在列表和搜索里，URL 仍能访问 |

## 版本（Version）

每次内容变化追加一个不可变的版本：`version_no` 从 1 递增，带 `label`（可选说明）、`content`、`content_sha`、`source_path`（来自仓库的文件路径，如果有）。

**什么算「没变」**：正文哈希相同即 `unchanged`，而且比较时忽略 Markdown 的 frontmatter——仓库回写会给文档加 frontmatter，同一份内容推回来不能变成新版本。

## 分类树与时间轴

- 左侧的**分类树**由所有在线文档的 `category` 汇聚而成：目录节点带子树计数，目录里直接列出文档（README 优先，然后按文件名的自然顺序，`02-x.md` 排在 `10-x.md` 前）。
- **时间轴** `/t` 把每一次发布（每个版本）按天分组，可按分类过滤。

## 状态（DocState）

文档可以按 `key` 存任意 JSON 值，两种作用域：

| scope | 存给谁 | 典型用途 |
|---|---|---|
| `me` | 当前读者（跨设备，因为存在服务端） | 个人进度、偏好、勾选 |
| `shared` | 所有读者共用一份 | 团队看板、共同备注、投票 |

值上限 64KB（`DOCSTATE_MAX_STATE_BYTES`），key 匹配 `^[\w.\-:]{1,200}$`。状态属于文档（slug），不属于版本：切换版本看到的是同一份状态。

## 沙箱

每篇文档在壳页的 `<iframe sandbox="allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox allow-modals">` 里运行，响应头再带一层 CSP `sandbox`。没有 `allow-same-origin`，文档的 origin 是 opaque 的：

- 读不到读者的 cookie，调不了站点 API；
- 只能 `postMessage` 给壳页，壳页只认自己 iframe 发来的消息，只代理当前文档的状态；
- 外链脚本只能来自 cdnjs 与 jsdelivr，`connect-src 'none'`。

细节见 [安全模型](security.md)。

## 身份与信任

- **读者**由身份模式决定：`none` 匿名（每个浏览器一个随机 id，让 `me` 作用域仍可用）、`fake` 演示身份、`header` 信任登录代理写入的邮箱头。
- **受信服务**（CI、MCP 服务器）用命名 token 调 API，替它转发的作者发布。
- **权限**默认全员可读可发；要接自己的规则，实现一个 `docstate.authorizer` entry point。

## 仓库与站点

站点可以从一个文档仓库导入（`docstate import`、`/api/import`），也可以把站上发布的文档**回写**到 GitHub 仓库（可选集成）。两个方向靠 `source_path` 与 `RepoBinding` 对上同一篇文档，所以来回同步不会产生重复或多余的版本。
