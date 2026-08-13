# PrizePass

比赛奖品兑换平台轻量版。管理员用单一环境变量密码管理比赛、六字段奖品、获奖人、兑换记录和通知；获奖人用一次性兑换码在 quota 与实时库存范围内一次选择多件奖品，并到固定地点自提。

## 技术栈与端口

- Vue 3 + TypeScript + Vite + Pinia + Tailwind CSS，开发端口 `5177`
- FastAPI + SQLAlchemy 2 + Alembic，API 端口 `8007`
- MySQL 8 / InnoDB / utf8mb4
- MySQL 通知任务表 + 单独 Python worker
- SMTP 多段 Email、email-poster 兼容 HTTP 转发与固定 Webhook

没有管理员用户表、Cookie、Token、JWT、RBAC、余额、多自提点、配送、复杂库存或 mock 后端。

## 本地启动（唯一入口）

要求 Python 3.12、Node.js、npm 和可连接的 MySQL 8。先准备环境：

```bash
cp .env.example .env
```

编辑 `.env`，至少填写 `DATABASE_URL`、`ADMIN_PASSWORD`，并把 `UPLOAD_DIR` 设为当前用户可写的持久化绝对路径。然后只运行：

```bash
./dev.sh
```

脚本会创建/复用 `.venv`、安装依赖、创建 `UPLOAD_DIR/prizes`，根据 `DATABASE_URL` 自动创建业务库及同名 `_test` 测试库，依次执行全部 Alembic 迁移，再同时启动：

- 前端：<http://localhost:5177>
- API 健康检查：<http://127.0.0.1:8007/api/health>
- 通知 worker

`Ctrl+C` 会停止三个进程。任一核心进程异常退出，脚本返回非零。

开发种子也通过同一入口执行；它幂等创建一场 active 比赛和三个奖品：

```bash
./dev.sh seed
```

## 环境变量

完整清单位于 `.env.example`。关键项：

- `DATABASE_URL`：MySQL PyMySQL URL；目标库可不存在，`dev.sh` 会创建。
- `ADMIN_PASSWORD`：每个 `/api/admin/*` 请求直接携带的密码。
- `PUBLIC_BASE_URL=http://localhost:5177`
- `APP_PORT=8007`
- `UPLOAD_DIR`：必须持久化并与 MySQL 同时间点备份。
- `SMTP_*`、`NOTIFICATION_EMAIL`、`WEBHOOK_URL`：通知目标和适配器配置。
- `EMAIL_POSTER_POST_URL`：email-poster 下游邮件网关地址；配置后，每条邮件通知会额外创建一个 `email_poster` 任务。
- `EMAIL_POSTER_PRESET`：`generic`（默认）、`smtogo`、`custom_example` 或 `none`。
- `EMAIL_POSTER_FROM_ADDRESS`：转发邮件的默认发件地址。
- `EMAIL_POSTER_HEADERS`、`EMAIL_POSTER_FIELDS`、`EMAIL_POSTER_EXTRA`：JSON 对象，语义分别对应 email-poster 的 `headers`、`fields`、`extra`。

例如 generic/Resend 风格网关：

```dotenv
EMAIL_POSTER_POST_URL=https://mail-gateway.example.com/send
EMAIL_POSTER_PRESET=generic
EMAIL_POSTER_FROM_ADDRESS=noreply@example.com
EMAIL_POSTER_HEADERS={"Authorization":"Bearer replace-me"}
```

管理后台为每个事件同时维护纯文本与可选 HTML 模板。SMTP 会发送 `multipart/alternative`（纯文本 + HTML）；email-poster 优先发送 HTML，HTML 关闭时使用纯文本字段；普通 Webhook 的 JSON 同时包含 `text` 与 `html`。HTML 变量会做实体转义，模板自身仍由管理员控制。

“场景通知路由”可为每个通知场景独立选择：SMTP → 获奖人、SMTP → 运营邮箱、email-poster → 获奖人、email-poster → 运营邮箱以及 Webhook。一个场景可同时选择多条路由，也可全部关闭；修改只影响之后创建的通知任务。默认路由如下：

- 兑换码发放、奖品待领取、兑换取消：邮件发给获奖人。
- 兑换已提交、兑换已领取：邮件发给 `NOTIFICATION_EMAIL`。
- 所有场景默认启用 Webhook；配置 email-poster 后，它与 SMTP 使用相同的默认收件对象。

密码只保存在管理员页面内存；兑换码只保存在兑换页面内存。刷新后均需重新输入。

## 测试与质量检查

先至少运行一次 `./dev.sh`，确保主库和 `_test` 测试库已初始化及迁移。之后执行：

```bash
cd backend
../.venv/bin/pytest -q

cd ../frontend
npm run lint
npm run typecheck
npm run build
```

后端测试只连接由开发库名派生的 `_test` 库，不使用 SQLite。覆盖表格原子导入、事务回滚、行锁并发、状态机、取消恢复、快照、通知任务重试与渠道隔离。

## 使用流程

1. 打开 `/admin`，输入 `ADMIN_PASSWORD`。
2. 创建比赛，设置单一自提地点、说明和截止时间。
3. 新增或导入奖品；本地图片先上传，再保存返回的 `/uploads/prizes/...` URL。
4. 在“获奖人”页下载模板，校验并确认导入。系统生成兑换码及 SMTP/Webhook 任务；配置 email-poster 后也会生成对应转发任务。
5. worker 发送任务；失败任务按 1 分钟、5 分钟重试，第三次失败后可在通知设置中手工重试。
6. 获奖人打开 `/redeem`，输入码、选择多种奖品、填写领取人信息并一次提交。
7. 管理员将兑换依次处理为待领取、已领取，或在领取前取消并恢复库存与兑换码。

## 表格与图片

- 导入仅接受 UTF-8 CSV 或首工作表 XLSX，最大 5 MB、10,000 数据行。
- 奖品表头：`name,image,real_value,redeem_value,stock,description`。
- 获奖人表头：`name,email,quota` 或 `external_id,name,email,quota`。
- 任一行错误会拒绝整个导入；确认接口会重新解析同一个文件。
- CSV 导出带 UTF-8 BOM；CSV/XLSX 均处理公式注入前缀。
- 图片仅接受 HTTPS 外链，或服务端按文件内容确认的 JPEG/PNG/WebP（最大 5 MB）。

## 生产部署

服务器需预装 Python 3.12、Node.js、npm、PM2、MySQL 及 Nginx/Caddy，并准备 `.env`。运行：

```bash
./deploy.sh
```

脚本安装锁定依赖、执行 `npm ci` 与生产构建、迁移数据库、检查上传目录、用 `ecosystem.config.cjs` 启动或重载且仅管理 `prizepass-api` 与 `prizepass-worker`，随后检查 8007 健康接口和 PM2 状态。它不会拉取代码、创建数据库、修改 Web 服务配置或删除上传文件。

Web 服务应将 `/api/` 代理到 `127.0.0.1:8007`，将 `/uploads/` 映射到 `UPLOAD_DIR`，其余路径提供 `frontend/dist/` 并启用 SPA fallback；生产环境必须使用 HTTPS。

## AC-01～AC-23 复现索引

| 验收项 | 自动化或复现方式 |
|---|---|
| AC-01～05 | `test_phase1.py`、`test_phase2.py`；后台创建比赛/奖品并上传合法与非法图片 |
| AC-06～10 | `test_phase3.py`、`test_phase6.py`；获奖人导入页与通知设置页 |
| AC-11～18 | `test_phase4.py`、`test_phase5.py`；含真实 MySQL 同码并发与快照测试 |
| AC-19～20 | `test_phase2.py`、`test_phase3.py`、`test_phase5.py`；分别下载 CSV/XLSX 检查 |
| AC-21 | `test_phase4.py`；公开响应无 `Set-Cookie` |
| AC-22 | `./dev.sh` 后检查 5177、8007、worker，再按 `Ctrl+C` |
| AC-23 | 在已配置服务器运行 `./deploy.sh`，检查健康接口与 `pm2 status` |
