# 部署：Kubernetes

`deploy/kubernetes/base` 是一个可直接 `kubectl apply -k` 的 kustomize base：Deployment（单副本 + PVC，SQLite）、Service、以及一个把配置注入为环境变量的 ConfigMap。生产建议：

1. 复制一个 overlay，把 `DOCSTATE_STORAGE_URL` 指向 PostgreSQL（Secret 注入），删掉 PVC，`replicas` 改为 2+，`strategy` 改为 RollingUpdate。
2. Ingress 放在登录代理后面（Cloudflare Access / oauth2-proxy / 网关），`DOCSTATE_AUTH_MODE=header`。
3. 把 `DOCSTATE_API_TOKENS`、数据库密码放进 Secret。

```bash
kubectl apply -k deploy/kubernetes/base
kubectl -n docstate get pods
```

## 迁移

启动时自动迁移（`DOCSTATE_AUTO_MIGRATE=true`）。更稳的做法是关掉它，用一个 Job 或 initContainer 跑：

```yaml
initContainers:
  - name: migrate
    image: ghcr.io/qiaob/docs-site:latest
    command: ["docstate", "migrate"]
    envFrom:
      - secretRef: { name: docstate }
```

## 探针

`/healthz` 探测存储连通，可同时做 readiness 与 liveness。

## 资源

站点很轻：`requests: 100m / 256Mi`，`limits: 1 / 512Mi` 足够；Markdown 渲染在请求路径上，大文档多的话再加。
