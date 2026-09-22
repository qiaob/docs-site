# 部署清单

| 文件 | 用途 |
|---|---|
| `docker-compose.postgres.yml` | 单机：Docstate + PostgreSQL |
| `kubernetes/base/` | kustomize base：Namespace、ConfigMap、Deployment（单副本 + PVC，SQLite）、Service |

说明见 [docs/deployment/docker.md](../docs/deployment/docker.md) 与 [docs/deployment/kubernetes.md](../docs/deployment/kubernetes.md)。
