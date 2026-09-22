# 写作：HTML 与 DocState

## 一篇合格的 HTML 文档

- **自包含**：样式和脚本内联；外链脚本 / 样式只能来自 `cdnjs.cloudflare.com`、`cdn.jsdelivr.net`（样式另加 Google Fonts），其它会被沙箱 CSP 拦下。
- 有 `<title>`：站点用它做标题（没有则找 `<h1>`，再没有用文件名）；`<meta name="description">` 做摘要。
- 不要假设自己有 cookie 或能 `fetch` 站点接口——文档在 opaque origin 的沙箱里，`connect-src 'none'`。
- 不需要自己的滚动条：站点按内容高度调整 iframe。
- 发布前用 `docs_check` / `dry_run` 看警告。

## DocState

站点注入的 `docbridge.js` 提供 `window.DocState`：

```js
const ctx = await DocState.ready;                      // {slug, version, viewer, base}
const mine = await DocState.get("progress", { scope: "me" });     // null 表示没存过
await DocState.set("progress", { step: 3 }, { scope: "me" });
await DocState.set("board", { todo: [...] }, { scope: "shared" });
const stop = DocState.subscribe("board", render, { scope: "shared", interval: 3000 });
DocState.viewer();                                     // 读者身份，用来显示"谁改的"
DocState.inShell;                                      // false：直接打开了 raw 页，状态只在内存里
```

| | `me` | `shared` |
|---|---|---|
| 谁看到 | 只有当前读者，跨设备 | 所有读者 |
| 典型用途 | 进度、偏好、个人勾选 | 团队看板、共同备注、投票 |
| 并发 | 无冲突 | 后写覆盖先写；需要合并的场景先 `get` 再 `set`，并用 `subscribe` 刷新 |

值是任意 JSON，单个 key 上限 64KB。状态属于文档而不是版本：发新版本后旧勾选还在，设计 key 时如果版本间结构变了，换个 key 名。

## 模式

**表单式勾选**

```js
DocState.ready.then(async () => {
  const state = (await DocState.get("checks", { scope: "me" })) || {};
  document.querySelectorAll("input[type=checkbox]").forEach((box) => {
    box.checked = !!state[box.id];
    box.onchange = async () => {
      state[box.id] = box.checked;
      await DocState.set("checks", state, { scope: "me" });
    };
  });
});
```

**共享看板**

```js
let board = (await DocState.get("board", { scope: "shared" })) || { columns: {} };
DocState.subscribe("board", (v) => { board = v || board; render(board); }, { scope: "shared" });
async function move(card, to) {
  board = (await DocState.get("board", { scope: "shared" })) || board;   // 先取最新
  // ...改 board...
  await DocState.set("board", board, { scope: "shared" });
}
```

**给 AI 的提示**：让模型生成 HTML 时告诉它「用 `window.DocState` 保存需要记住的读者操作，`scope: "me"` 按人、`scope: "shared"` 全员；外链脚本只用 cdnjs / jsdelivr」。示例见 `examples/docs/docstate-demo.html` 与 `interactive-lab.html`。
