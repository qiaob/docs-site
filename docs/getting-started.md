# 快速上手

## 1. 安装并启动

任选一种：

```bash
# pip / uv
pip install "docstate[postgres]"        # SQLite 不需要任何额外驱动，postgres 是可选 extra
docstate serve                          # http://localhost:8787
```

```bash
# Docker（仓库内）
make up                                 # 构建镜像并启动，SQLite 放在 ./data
make import                             # 导入 examples/docs 里的示例文档
```

默认配置：SQLite `data/docstate.db`、`fake` 身份模式（顶栏可切换演示读者）、界面语言英文。改语言：`DOCSTATE_LANG=zh-CN`。

`docstate check` 打印解析后的配置并探测数据库，部署排障先跑它。

## 2. 发布第一篇

```bash
echo '# 我的第一篇\n\n- [ ] 读完这页\n- [ ] 发一篇 HTML' > first.md
docstate publish first.md --category guides
#   created      v1  http://localhost:8787/d/first
```

打开这个 URL：任务列表可以勾选，刷新后还在——这就是 DocState 在 Markdown 上的零代码形态，默认按读者各存一份。

再发一次同样的文件，返回 `unchanged`；改点内容再发，返回 `new_version`，右上角的版本下拉里能切回 v1。

## 3. 发一篇带状态的 HTML

任何自包含的 HTML 都行（脚本、样式内联，外链脚本只能来自 cdnjs / jsdelivr）。站点会在 `</head>` 前注入 `docbridge.js`，于是页面里就有了 `window.DocState`：

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>发布前检查</title></head>
<body>
<label><input type="checkbox" id="c1"> 跑过测试</label>
<script>
  const box = document.getElementById('c1');
  DocState.ready.then(async () => {
    box.checked = !!(await DocState.get('checked', { scope: 'me' }));
    box.onchange = () => DocState.set('checked', box.checked, { scope: 'me' });
  });
</script>
</body></html>
```

```bash
docstate publish checklist.html --category guides --title "发布前检查"
```

`scope: "me"` 按读者存，`scope: "shared"` 全员一份；`DocState.subscribe` 轮询别人的改动。完整 API 见 [写作 · HTML 与 DocState](writing/html-docstate.md)。

## 4. 让 agent 来发

```bash
claude mcp add docstate -e DOCSTATE_URL=http://localhost:8787 -- uvx docstate-mcp
```

然后在 Claude Code 里说「把刚生成的报告发到 analytics/reports」。agent 会调 `docs_check` 看警告，再调 `docs_publish` 拿 URL。详见 [MCP 服务器](mcp.md)。

## 5. 导入一个文档仓库

```bash
docstate import ~/repos/team-docs            # 目录 = 分类，文件名 = slug，frontmatter = 元信息
docstate import ~/repos/team-docs --only guides/ -v
```

可以反复执行：内容没变的文件返回 `unchanged`。仓库里每个目录的 `README.md` 会显示在对应分类页的顶部。

## 下一步

- 部署到服务器：[Docker](deployment/docker.md) / [Kubernetes](deployment/kubernetes.md)，前面放登录代理并把 `DOCSTATE_AUTH_MODE` 设为 `header`。
- 换数据库：`DOCSTATE_STORAGE_URL=postgresql://user:pw@host/db`，启动时自动迁移（或 `docstate migrate`）。
- 给 CI / agent 发 token：`DOCSTATE_API_TOKENS=ci:<随机串>,agent:<随机串>`。
