# docbridge 协议

`docbridge.js` 由站点注入到每篇文档里（Markdown 渲染页与原样 HTML 都有）。文档在沙箱 iframe 里，只能 `postMessage` 给壳页；这份协议就是两边的全部约定。所有消息带 `__docbridge: 1`。

## 文档 → 壳页

| type | 载荷 | 含义 |
|---|---|---|
| `ready` | — | 文档就位，请求上下文；壳页未应答时每 400ms 重发，最多 8 次 |
| `state.get` | `{id, payload: {key, scope}}` | 读状态 |
| `state.set` | `{id, payload: {key, scope, value}}` | 写状态 |
| `height` | `{height}` | 内容高度变化（壳页据此调整 iframe，文档没有自己的滚动条） |
| `toc` | `{items: [{level, text, id, top}]}` | 标题列表（h1–h3，多个 h1 才含 h1），壳页渲染右侧目录 |
| `navigate` | `{href}` | 点击了站内链接（`/d/…`、`/c/…`、`/t…`、`/`），请壳页导航 |
| `wheel` | — | 收到了一次滚轮事件；壳页据此把后续滚轮事件留在自己这一层 |

## 壳页 → 文档

| type | 载荷 | 含义 |
|---|---|---|
| `ctx` | `{payload: {slug, version, viewer, base}}` | 对 `ready` 的应答；`viewer` 是读者身份，`base` 是站点 base URL（用于识别写成完整 URL 的站内链接） |
| `reply` | `{id, result, error}` | 对 `state.get` / `state.set` 的应答 |
| `remeasure` | — | 壳页改了 iframe 宽度（全屏等），请重报高度与目录 |

## 文档侧 API（`window.DocState`）

```js
DocState.ready                                   // Promise<ctx>
DocState.inShell                                 // false = 直接打开 raw 页，状态退化为本页内存
DocState.viewer()                                // 读者身份（ready 之后）
await DocState.get(key, { scope })               // scope: "me" | "shared"，默认 "me"
await DocState.set(key, value, { scope })
DocState.subscribe(key, fn, { scope, interval }) // 轮询（默认 4s），返回取消函数
```

请求 8 秒没有应答会 reject。

## 安全约束

- 壳页只接受来自自己 iframe（`ev.source === frame.contentWindow`）的消息，只代理当前文档的 slug。
- 文档拿不到 cookie，所有状态读写都由壳页带会话完成。
- 站外链接由文档侧改为 `target=_blank rel=noopener noreferrer`，站内链接交壳页导航。
