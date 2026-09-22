# 扩展：加一个存储后端

存储是两个端口：`DocumentStore`（文档、版本、仓库绑定）和 `StateStore`（文档状态），定义在 `docstate/storage/base.py`。`open_storage(url)` 按 URL scheme 选适配器：`sqlite / postgresql / mysql` 是 SQL 适配器，`memory` 是内存适配器，其它 scheme 去 `docstate.storage` entry point 组里找。

## 步骤

1. **实现两个协议**。看 `storage/memory.py`——它是最小的完整实现（约 200 行），每个方法的语义写在 `base.py` 的 docstring 里。要点：
   - `list()` 只返回在线文档、按 `updated_at` 倒序；`iter_all()` 含归档、正序。
   - `by_source_path()` 大小写不敏感，先查版本的 `source_path`，再查绑定的 `path`。
   - `versions()` 最新在前、含正文；`get_version(slug, None)` 是最新版。
   - `transaction()` 让块内的写一起提交；做不到就当 no-op（内存适配器就是）。
   - `save_repo_binding()` 要给 `updated_at` 盖时间戳。
2. **提供一个 `Storage`**：带 `docs`、`state`、`init()`、`ping()`、`close()`、`describe()`，以及给测试用的 `clear()`。
3. **写工厂** `open_xxx_storage(url, *, state_url="", **options)`，注册 entry point：

   ```toml
   [project.entry-points."docstate.storage"]
   dynamodb = "docstate_dynamodb:open_storage"
   ```

4. **跑契约测试**。把你的后端加进 `packages/docstate/tests/storage/test_contract.py` 的 `BACKENDS`（或在你自己的包里复制这份测试），全绿即合格。
5. 配置：`DOCSTATE_STORAGE_URL=dynamodb://…`。

## 只做状态后端

状态和文档可以分开：`DOCSTATE_STATE_URL` 指向另一个 URL 时，`open_storage` 会把 `state_url` 传给文档适配器的工厂。SQL 适配器对此的处理是给状态单独建一个 engine；如果你只想给状态换后端（比如 Redis），可以实现一个只带 `StateStore` 的适配器，并在文档适配器的工厂里按 `state_url` 的 scheme 组合。

也可以不写 Python：壳页只依赖 [State API](../protocol/state-api.md) 两个 HTTP 请求，一个独立服务实现它们就行（静态托管场景就是这么做的）。

## SQL 适配器的迁移

改了表结构：

```bash
# 在 packages/docstate 下，用一个临时 SQLite 库生成迁移脚本
uv run alembic -c /dev/null ...   # 建议直接手写 versions/000N_xxx.py，模板见 script.py.mako
```

脚本里用 `_names()` 拿到 `prefix` 与 `schema`，所有表名写成 `f"{prefix}docs"`，这样表前缀与独立 schema 的部署都能迁移。`render_as_batch` 在 SQLite 上自动开启，`ALTER` 会走批处理。
