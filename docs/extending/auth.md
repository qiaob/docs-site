# 扩展：身份与权限

## 读者身份

三种内置模式（`DOCSTATE_AUTH_MODE`）：

| 模式 | 读者是谁 | 用在哪 |
|---|---|---|
| `none` | 匿名；每个浏览器一个随机 id，让 `me` 作用域可用 | 公开站 |
| `fake` | 顶栏可选的演示身份 | 本地开发、演示 |
| `header` | 登录代理写入的邮箱头（可选共享密钥头校验） | 生产：Cloudflare Access、oauth2-proxy、Tailscale、你自己的网关 |

`header` 模式的常见配置：

```bash
# Cloudflare Access
DOCSTATE_AUTH_MODE=header
DOCSTATE_AUTH_HEADER=Cf-Access-Authenticated-User-Email
# oauth2-proxy
DOCSTATE_AUTH_HEADER=X-Forwarded-Email
# 你自己的网关，再带一个共享密钥头证明来路
DOCSTATE_AUTH_PROXY_SECRET=<随机串>
DOCSTATE_AUTH_SECRET_HEADER=X-My-Gateway-Secret
DOCSTATE_ALLOWED_DOMAINS=example.com
DOCSTATE_LOGIN_URL=https://sso.example.com/login
DOCSTATE_LOGOUT_URL=https://sso.example.com/logout
```

站点自己做登录（OIDC）在路线图上。

## 权限

三个权限点：`read`（打开站点、读文档、存自己的状态）、`publish`（通过 API 发布与改元信息）、`admin`（归档、改别人的文档）。默认登录即全部拥有。

接自己的规则：实现 `callable(principal: str, permission: str) -> bool`，注册 entry point 并用 `DOCSTATE_AUTHORIZER` 选中：

```python
# my_authz.py
READERS = {"example.com"}
PUBLISHERS = {"alice@example.com"}

def authorize(principal: str, permission: str) -> bool:
    domain = principal.rpartition("@")[2]
    if permission == "read":
        return domain in READERS
    if permission == "publish":
        return principal in PUBLISHERS
    return False
```

```toml
[project.entry-points."docstate.authorizer"]
team = "my_authz:authorize"
```

```bash
DOCSTATE_AUTHORIZER=team
```

被拒绝的读者看到 403 页面；API 调用得到 `{"error": "..."}`。受信 token 的调用方不经过这个 hook——它替谁发布由它自己负责。

## 受信服务

给 CI、MCP 服务器、其它系统各发一个命名 token：

```bash
DOCSTATE_API_TOKENS="ci:$(openssl rand -hex 24),agent:$(openssl rand -hex 24)"
```

调用时带 `X-Docstate-Token`（或 `Authorization: Bearer`），可选 `X-Docstate-Author` 指明作者；审计日志里能看到 token 名。
