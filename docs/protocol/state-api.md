# State API 协议

壳页对状态后端的依赖只有两个请求。任何实现了它们的服务都能当 Docstate 的状态后端——本站自带的实现、将来的 Cloudflare Pages Function、你自己写的任何东西。

## 请求

```
GET  /api/state/{slug}/{key}?scope=me|shared
PUT  /api/state/{slug}/{key}?scope=me|shared        body: {"value": <任意 JSON>}
     必带头 X-Requested-With: docstate
```

## 响应

```json
{
  "key": "checklist",
  "scope": "me",
  "value": {"0": true},
  "updated_by": "alice@example.com",
  "updated_at": "2026-09-22T03:40:00Z"
}
```

没有值时 `value`、`updated_by`、`updated_at` 为 `null`。

## 规则

| 项 | 约定 |
|---|---|
| `slug` | 文档 slug，不存在返回 404 |
| `key` | `^[\w.\-:]{1,200}$`，否则 400 |
| `scope` | `me`：以当前读者为 owner；`shared`：owner 为空字符串。其它值按 `me` 处理 |
| 身份 | 服务端决定：会话（server 模式）、登录代理的邮箱头、`Cf-Access-Authenticated-User-Email`（Cloudflare Access）、或匿名 id cookie |
| 大小 | body 超过 `DOCSTATE_MAX_STATE_BYTES`（默认 64KB）返回 413 |
| CSRF | PUT 缺少 `X-Requested-With: docstate` 返回 403 |
| 读权限 | 读者必须能读这篇文档（`read` 权限） |

## 实现清单

一个最小后端要做的事：按 `(slug, key, owner)` 存取一个 JSON 值，记录 `updated_by` 与 `updated_at`；校验 key 与大小；从请求里确定读者身份。参考实现：`docstate/server/api.py` 的 `state_get` / `state_put` 与 `docstate/storage/base.py` 的 `StateStore` 协议。
