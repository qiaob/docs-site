# 安全模型

## 威胁模型

站点上任何人（包括 AI）都能发布带脚本的 HTML。要防的是：一篇文档窃取读者的会话、替读者调站点接口、篡改别人的状态、把读者带去别的地方而读者不知情。

## 沙箱

- 文档在 `<iframe sandbox="allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox allow-modals">` 里，**没有 `allow-same-origin`**：文档的 origin 是 opaque 的，读不到 cookie，`fetch('/api/...')` 会被当作跨站请求且带不上会话。
- `/raw/<slug>/<n>` 的响应头再加 CSP：`sandbox …; frame-ancestors 'self'; connect-src 'none'; script-src 'self' 'unsafe-inline' cdnjs jsdelivr; …`。文档只能被本站的壳页嵌入，脚本只能来自两家 CDN，不能发起任何网络请求。
- `docbridge.js` 内联注入而不是 `<script src>`：opaque origin 的子资源请求不带登录代理的 SameSite cookie，外链的话在代理后面会 401。

## 壳页与状态

- 壳页只处理 `ev.source === frame.contentWindow` 的消息，只代理**当前文档**的状态；文档 A 拿不到文档 B 的状态。
- 状态写接口要求 `X-Requested-With: docstate` 头：跨站表单发不出自定义头，这就是 CSRF 防护。
- 状态值上限 64KB，key 有正则限制。
- `me` 作用域的 owner 是服务端从会话/头里得到的读者身份，文档没法冒充别人。

## 身份

- `fake` 模式任何人都能选任意身份，**只用于本地**；`docstate check` 和启动日志会在非 localhost 的 base_url 下警告。
- `header` 模式只在站点**只能**经过登录代理访问时才安全。如果 pod 可能被直连，配置 `DOCSTATE_AUTH_PROXY_SECRET`，让代理带一个共享密钥头。
- `none` 模式是公开站：匿名 id 只用来让 `me` 作用域可用，不构成身份。

## 受信服务

- API token 在服务端用常量时间比较，且对所有 token 都比一遍，避免时序泄露。
- 受信调用方替谁发布由它自己负责（它转发的作者头）；不配置 token 时只有 fake 模式把调用方当受信。

## 外链

文档里指向站外的链接在新标签页打开，且沙箱允许弹窗逃离沙箱（否则目标站会以 opaque origin 加载、没有登录态）；站内链接由壳页导航，不在 iframe 里跳。

## 静态托管下的退化（路线图）

GitHub Pages 这类平台设不了响应头：iframe 的 `sandbox` 属性依然生效（这是 opaque origin 的来源，也是真正承重的一层），CSP 退化为 raw 文档里的 `<meta http-equiv>`；Cloudflare / Netlify 可用 `_headers` 恢复完整响应头。

## 报告漏洞

见 [SECURITY.md](../SECURITY.md)。
