# 比赛奖品兑换平台——轻量版 PRD 与实现规格

## 0. 文档用途

本文档是可以直接交给编码 AI 开发的冻结版需求。除非本文明确要求，否则不要增加角色、配置项、页面、状态、抽象层或基础设施。

- 版本：v1.0
- 状态：已冻结，可开发
- 定位：单管理员使用的轻量级奖品兑换工具
- 原则：优先完成真实可运行、可测试的业务闭环，不建设通用企业平台

## 1. 一句话需求

管理员创建比赛和奖品，导入包含获奖人姓名、邮箱和 quota 的 CSV/XLSX。系统为每人生成唯一兑换码，通过 Email 自动发码，并向固定 Webhook 推送相同通知文本。获奖人输入兑换码后，可以在一次兑换中选择多个奖品及数量，只要抵扣价值总和不超过 quota 且库存足够；提交后由管理员备货并完成自提。

## 2. 固定业务规则

以下规则已经确定，实现时不得改成其他模型。

1. 系统只有两种访问方式：
   - 管理员输入一个指定密码进入后台；前端在每个后台 API 请求中直接携带该密码。
   - 兑换者输入兑换码进入兑换页面；前端在每个兑换 API 请求中直接携带该兑换码。
2. 不建立管理员用户表，不支持多管理员账号，不支持 RBAC。
3. 管理员密码从环境变量 `ADMIN_PASSWORD` 读取。
4. 系统支持多个比赛，每个比赛独立管理奖品、获奖人、兑换码和兑换记录。
5. 每个比赛只有一个固定自提地点和一段自提说明。
6. 每名获奖人对应一个 quota 和一个兑换码。
7. quota 和奖品的抵扣价值均为大于 0 的整数，使用相同单位“额度”。
8. 一个兑换码可以在一次提交中兑换多个奖品，也可以兑换同一奖品多件。
9. 总抵扣额度为 `sum(奖品抵扣价值 × 数量)`，不得超过兑换码 quota。
10. 一个兑换码只能成功提交一次。提交成功后兑换码失效。
11. 未使用完的 quota 不返还、不保留、不生成余额。
12. 不允许现金补差价。
13. 奖品只维护一个简单库存整数；提交时扣库存，取消时恢复库存。
14. 不支持仓库、预占库存、库存批次、序列号或库存流水。
15. 获奖人和奖品支持 CSV/XLSX 表格导入。全部校验通过后才写入数据库。
16. 所有兑换均为自提，不支持地址、快递、物流和运费。
17. 兑换者提交时只填写姓名、手机号和可选备注。
18. Email 与 Webhook 使用同一个通知模型：向一个明确目标发送一段已经渲染好的纯文本。
19. Email 与 Webhook 共用通知任务表、worker、发送状态和重试逻辑。
20. 通知模板只有固定的几种事件类型，可编辑纯文本，不做版本管理或富文本编辑器。
21. 不需要报表、审计日志、仪表盘、二次验证、验证码、设备识别或限流。
22. 不使用 Cookie、服务器会话、Bearer Token、OAuth 或 JWT，也不存在用户管理。
23. 表格导出是原始业务数据导出，不做图表、汇总分析或报表系统。

## 3. 产品范围

### 3.1 必须实现

- 管理员密码入口；刷新页面后重新输入密码。
- 比赛的创建、编辑、开启和关闭。
- 每场比赛配置一个自提地点、自提说明和兑换截止时间。
- 奖品管理：新增、查看、编辑和删除。
- 奖品图片支持任意 HTTPS 图片外链或本地文件上传，两者最终统一为一个可访问的图片 URL。
- 获奖人 CSV/XLSX 模板下载、上传、预览、校验、确认导入和逐行错误展示。
- 奖品 CSV/XLSX 模板下载、上传、预览、校验和确认导入。
- 奖品、获奖人和兑换记录的 CSV/XLSX 原始数据导出。
- 为新导入的每名获奖人自动生成一个唯一兑换码。
- 导入成功后自动创建 Email 和 Webhook 通知任务。
- 查看获奖人的 quota、兑换码和通知状态。
- 验证兑换码并按 quota 与库存展示奖品。
- 购物篮支持多个奖品和数量调整。
- 原子化提交兑换，防止重复兑换、超 quota 和超卖。
- 管理员查看兑换记录并更新为待领取、已领取或已取消。
- Email 与 Webhook 的文本模板编辑、测试发送、失败记录和重试。

### 3.2 明确不实现

- 管理员账号管理、多管理员、角色权限和 RBAC。
- 兑换者账号、用户中心和订单历史页面。
- 一个兑换码分多次消费或保留余额。
- 多自提点。
- 支付、退款、采购、供应商和补差价。
- 配送、地址、物流和快递。
- 仓库、库存预占、库存批次、序列号和库存流水。
- 兑换记录反向导入、外部导入 API 和第三方业务数据同步。
- 短信、站内通知或其他通知渠道。
- HTML 邮件编辑器、附件、模板版本和审批。
- Webhook 签名、订阅管理、多个 Webhook 地址和复杂事件总线。
- 报表、审计日志和复杂统计。
- 二次验证、短信验证码、设备识别和限流。
- 商品网页抓取、解析、价格同步、库存同步或商品导入。

## 4. 名词和数值定义

| 名词 | 定义 |
|---|---|
| quota | 某个兑换码最多可以消耗的额度，正整数。 |
| 真实价值 | 奖品的实际参考价值，使用人民币“分”保存；后台可输入两位小数金额。只用于展示，不参与 quota 计算。 |
| 抵扣价值 | 兑换该奖品每件消耗的 quota，正整数。 |
| 库存 | 当前剩余可兑换数量，非负整数。 |
| 兑换记录 | 某个兑换码一次性提交的兑换单，包含一个或多个奖品行。 |
| 通知任务 | 将某个业务事件的一段文本，通过 Email 或 Webhook 发送到指定目标的任务。 |

示例：某奖品真实价值为 ¥299.00，抵扣价值为 250；quota 为 500 的兑换码可以兑换两件该奖品，合计消耗 500 额度。

## 5. 访问模型

### 5.1 管理员

- 访问 `/admin` 时显示密码入口，输入环境变量 `ADMIN_PASSWORD` 对应的密码。
- 前端只把密码保存在当前页面的内存中，不写 Cookie、localStorage 或 sessionStorage。
- 前端为每个 `/api/admin/*` 请求添加 `X-Admin-Password` 请求头。
- 后端使用常量时间比较请求头与 `ADMIN_PASSWORD`；不匹配时返回 401。
- 刷新或关闭页面后需要重新输入密码。
- 没有登录接口、注销接口、用户表、Token 和服务器会话。
- 生产环境必须使用 HTTPS，避免密码在传输过程中泄露。

### 5.2 兑换者

- 访问 `/redeem`，输入兑换码。
- 前端只在当前页面内存中保存兑换码。
- 验证、奖品列表和提交接口都通过 `X-Redemption-Code` 请求头携带兑换码。
- 刷新或关闭页面后需要重新输入兑换码。
- 不使用 Cookie、Token 或服务器会话。
- 兑换者不注册、不登录，也没有用户中心。

## 6. 核心业务流程

### 6.1 管理比赛和奖品

1. 管理员创建比赛，填写名称、说明、兑换截止时间、固定自提地点和自提说明。
2. 管理员为比赛创建奖品。
3. 每个奖品只录入六项业务信息：名字、图片、真实价值、抵扣价值、库存、描述。
4. 图片可以粘贴任意 HTTPS 图片 URL，也可以上传本地图片文件；二者只能选择一种作为当前图片。
5. 管理员确认比赛信息和奖品后开启比赛。
6. 只有状态为 `active` 且未超过兑换截止时间的比赛允许兑换。

### 6.2 导入获奖人并自动发码

支持 CSV 和 XLSX。CSV 必须使用 UTF-8 编码；两种格式的第一行均为表头，XLSX 只读取第一个工作表。

必填列：

```csv
name,email,quota
张三,zhangsan@example.com,500
李四,lisi@example.com,300
```

可选列：

```csv
external_id,name,email,quota
A001,张三,zhangsan@example.com,500
```

导入规则：

1. `name` 去除首尾空格后不能为空。
2. `email` 转为小写并去除首尾空格，必须是基本合法的邮箱格式。
3. `quota` 必须是大于 0 的整数。
4. 同一个导入文件内不允许重复的 `external_id` 或规范化 email。
5. 同一比赛内，有 `external_id` 时以它作为身份键；否则以规范化 email 作为身份键。
6. 身份键已存在时，该行报重复错误，不生成新码，也不重复发送通知。
7. 导入采用全有或全无规则：任意一行有错误，本次不写入任何获奖人、兑换码或通知任务。
8. 全部通过后，在一个数据库事务中创建获奖人、兑换码和对应通知任务。
9. 每名获奖人生成一个全局唯一、不可顺序猜测的兑换码。
10. 事务提交后，通知 worker 自动发送任务。
11. 某个任务发送失败不影响其他任务；管理员可以查看失败原因并重试。

### 6.3 导入奖品

支持 CSV 和 XLSX，表头固定为：

```csv
name,image,real_value,redeem_value,stock,description
保温杯,https://example.com/cup.jpg,199.00,150,20,黑色保温杯
```

规则：

1. 六列与奖品表单完全一致，不接受其他业务字段。
2. `image` 接受 HTTPS URL 或系统中已经存在的 `/uploads/prizes/...` 路径。
3. 新的本地图片文件必须先通过图片上传功能上传，再把返回路径填入表格；不把图片二进制嵌入 XLSX。
4. `real_value` 接受最多两位小数的非负人民币金额，导入时转换为分。
5. `redeem_value` 必须是大于 0 的整数，`stock` 必须是非负整数。
6. 导入只新增奖品，不根据名称覆盖已有奖品。
7. 导入采用全有或全无规则；任意行错误时不新增任何奖品。
8. 确认页显示规范化后的所有行和错误位置。

### 6.4 兑换多个奖品

1. 兑换者输入兑换码。
2. 系统验证兑换码为 `issued`、比赛为 `active` 且未超过截止时间。
3. 系统显示比赛、quota、自提信息和当前有库存的奖品。
4. 只显示库存大于 0 且单件抵扣价值不超过该码 quota 的奖品。
5. 兑换者选择一个或多个奖品并调整数量。
6. 页面实时显示已用额度和剩余额度。
7. 总抵扣额度超过 quota 或数量超过库存时，禁止进入确认页。
8. 兑换者填写姓名、手机号和可选备注。
9. 确认奖品、数量、总抵扣额度和自提说明后提交。
10. 系统提交成功后显示兑换单号并使兑换码失效。
11. 系统创建“兑换已提交”Email 和 Webhook 通知任务。

### 6.5 管理员处理兑换

1. 新兑换记录状态为 `submitted`。
2. 管理员备货后将其改为 `ready`，系统通知获奖人并推送 Webhook。
3. 兑换者到场后，管理员将其改为 `picked_up`，系统向运营邮箱和 Webhook 发送通知。
4. 管理员可以在领取前将记录改为 `cancelled`，系统恢复库存和兑换码，并通知获奖人及 Webhook。
5. `picked_up` 不能取消，也不能重复领取。

## 7. 固定通知规则

Email 和 Webhook 不是两个独立业务系统。业务代码只负责产生“事件 + 目标 + 文本”，worker 根据渠道选择发送适配器。

### 7.1 事件与目标

| 事件 | Email 目标 | Webhook 目标 | 触发时机 |
|---|---|---|---|
| `code_issued` | 该获奖人的 email | 固定 `WEBHOOK_URL` | 获奖人成功导入并生成兑换码后 |
| `redemption_submitted` | 固定 `NOTIFICATION_EMAIL` | 固定 `WEBHOOK_URL` | 兑换提交事务成功后 |
| `redemption_ready` | 该获奖人的 email | 固定 `WEBHOOK_URL` | 管理员标记待领取后 |
| `redemption_picked_up` | 固定 `NOTIFICATION_EMAIL` | 固定 `WEBHOOK_URL` | 管理员标记已领取后 |
| `redemption_cancelled` | 该获奖人的 email | 固定 `WEBHOOK_URL` | 管理员取消兑换后 |

每个事件生成两个独立任务：一个 `email` 任务和一个 `webhook` 任务。某一渠道失败不影响另一渠道。

### 7.2 通知文本模板

系统预置上述五种事件的纯文本模板。管理员可以修改模板内容，但不能新增事件类型。Email 正文和 Webhook 的 `text` 字段必须使用同一份渲染结果。

允许变量：

```text
{{winner_name}}
{{winner_email}}
{{event_name}}
{{code}}
{{quota}}
{{redemption_url}}
{{deadline}}
{{order_no}}
{{items_summary}}
{{total_redeem_value}}
{{unused_quota}}
{{status}}
{{pickup_location}}
{{pickup_instructions}}
```

- 保存模板时拒绝未知变量。
- 不同事件只能使用其上下文中存在的变量。
- Email 主题由系统根据事件固定生成，例如 `[PrizePass] 兑换码通知`，不单独配置。
- Webhook 以 HTTP POST 发送 JSON：

```json
{
  "event_type": "redemption_submitted",
  "text": "张三已提交兑换……",
  "occurred_at": "2026-08-13T10:30:00Z"
}
```

- Webhook 成功条件为 HTTP 2xx。
- 不做 Webhook 签名和订阅管理，只使用一个固定 URL。

## 8. 状态定义

### 8.1 比赛状态

```text
draft -> active
active -> closed
closed -> active
```

- `draft`：可编辑，不允许兑换。
- `active`：允许兑换。
- `closed`：不允许新兑换，历史数据仍可查看。
- 即使为 `active`，超过 `redemption_deadline` 后也不能新兑换。

### 8.2 兑换码状态

```text
issued -> redeemed
issued -> disabled
disabled -> issued
redeemed -> issued   仅在对应兑换被取消时
```

### 8.3 兑换记录状态

```text
submitted -> ready
submitted -> cancelled
ready -> picked_up
ready -> cancelled
```

- `picked_up` 和 `cancelled` 均为终态。

### 8.4 通知任务状态

```text
pending -> sending -> sent
pending -> sending -> retrying -> sending
pending -> sending -> failed
failed -> pending   管理员手工重试
```

## 9. 页面规格

### 9.1 管理后台

#### A. 管理员密码入口 `/admin`

- 密码输入框、进入后台按钮和错误提示。
- 密码只保存在当前页面内存中，刷新后重新输入。

#### B. 比赛列表 `/admin/events`

- 展示比赛名称、状态、截止时间、获奖人数和兑换数量。
- 支持新建比赛和进入比赛详情。
- 两个数量只是列表计数，不是报表功能。

#### C. 比赛详情 `/admin/events/:id`

比赛字段：名称、说明、兑换截止时间、自提地点、自提说明、状态。

页面包含四个页签：奖品、获奖人、兑换记录、比赛设置。

#### D. 奖品管理

每个奖品的表单只能包含以下六个业务字段：

| 字段 | 要求 |
|---|---|
| 名字 `name` | 必填，1～200 字符。 |
| 图片 `image` | 必填；选择 HTTPS 外链或本地上传。 |
| 真实价值 `real_value` | 必填，大于等于 0，人民币金额，界面允许两位小数。 |
| 抵扣价值 `redeem_value` | 必填，大于 0 的整数。 |
| 库存 `stock` | 必填，大于等于 0 的整数。 |
| 描述 `description` | 可选，最多 5000 字符，纯文本。 |

操作：新增、查看、编辑、删除。

表格操作：

- 下载 CSV 模板或 XLSX 模板。
- 上传 CSV/XLSX 后预览并确认导入。
- 导出当前比赛的全部奖品为 CSV 或 XLSX。
- 导出字段固定为 `name,image,real_value,redeem_value,stock,description`。
- `real_value` 导入导出均使用界面金额格式，例如 `199.00`，而不是数据库中的分。

- 没有被任何兑换记录引用的奖品可以删除。
- 已被兑换记录引用的奖品不可删除，但仍可编辑；历史兑换明细使用提交时快照，不受编辑影响。
- 库存为 0 时不展示给兑换者。
- 不设置奖品分类、规格、SKU、来源链接、参考价、上下架状态或其他字段。

图片规则：

- 外链仅接受 `https://` URL，不针对任何网站写特殊逻辑。
- 本地上传只接受 JPEG、PNG、WebP，单文件最大 5 MB。
- 服务端读取文件内容判断 MIME，不只相信扩展名。
- 上传文件使用随机文件名，保存在 `${UPLOAD_DIR}/prizes/`。
- `UPLOAD_DIR` 必须位于持久化目录，不能放在前端构建目录、临时目录或每次发布会被覆盖的目录中。
- 后端通过 `/uploads/prizes/{filename}` 提供图片访问。
- 数据库的 `image` 字段统一保存外链 URL 或站内 `/uploads/...` 路径。
- 上传新图片替换旧的本地图片时，旧文件只有在不再被任何奖品或兑换明细快照引用后才删除。

#### E. 获奖人和表格导入导出

- 下载 CSV 模板或 XLSX 模板。
- 上传 CSV/XLSX 后立即显示预览或逐行错误。
- 有错误时不能确认导入。
- 全部有效时显示总人数和 quota 合计并允许确认。
- 列表显示姓名、邮箱、quota、兑换码、兑换码状态和最近通知状态。
- 支持复制单个兑换码。
- 支持导出当前比赛的全部获奖人数据为 CSV 或 XLSX。
- 导出字段固定为 `external_id,name,email,quota,code,code_status,email_notification_status,webhook_notification_status,created_at`。
- 获奖人只是导入的收件人记录，不是用户，不提供用户创建、密码、角色、登录或个人资料管理。

#### F. 兑换记录

- 展示兑换单号、提交人、手机号、奖品摘要、总抵扣额度、状态和提交时间。
- 支持按状态筛选和按兑换单号搜索。
- 详情展示奖品快照、数量、抵扣价值、小计、总消耗和自提信息。
- 只允许执行第 8.3 节规定的状态变化。
- 支持导出当前比赛的全部兑换记录为 CSV 或 XLSX。
- 导出按奖品明细展开，一件兑换单含多个奖品时输出多行；每行包含兑换单公共字段和一条奖品明细。
- 导出字段固定为 `order_no,status,winner_name,winner_email,contact_name,contact_phone,note,quota,total_redeem_value,unused_quota,prize_name,real_value,redeem_value,quantity,line_redeem_value,created_at,picked_up_at,cancelled_at`。

#### G. 通知设置 `/admin/settings/notifications`

- 显示 SMTP、运营通知邮箱和 Webhook 是否已通过环境变量配置。
- 不显示 SMTP 密码原文。
- 编辑五种事件的纯文本模板。
- 分别提供 Email 测试和 Webhook 测试按钮。
- Email 测试时由管理员输入收件地址。
- 测试也创建普通通知任务，不在 HTTP 请求中直接发送。
- 页面展示最近通知任务及状态、渠道、脱敏目标、失败原因和重试按钮。

### 9.2 兑换页面

#### A. 输入兑换码 `/redeem`

- 兑换码输入框和验证按钮。
- 失败统一显示“兑换码无效或当前不可使用”。

#### B. 选择奖品 `/redeem/prizes`

- 显示比赛名称、总 quota、已使用额度和剩余额度。
- 奖品卡片展示图片、名字、描述、真实价值、抵扣价值、库存和数量选择器。
- 支持选择多个奖品；购物篮为空时不能继续。

#### C. 填写信息 `/redeem/confirm`

- 姓名：必填，1～100 字符。
- 手机号：必填，5～30 字符，只做长度和允许字符校验。
- 备注：可选，最多 500 字符。
- 展示奖品、数量、抵扣价值、小计、总消耗、剩余额度和自提信息。
- 提交按钮防止连续点击，但后端仍必须保证幂等和事务安全。

#### D. 成功页 `/redeem/success`

- 展示兑换单号、状态、自提地点和自提说明。
- 不提供订单中心或再次编辑入口。

## 10. 数据模型

使用 MySQL 8.x、InnoDB 和 `utf8mb4`。所有时间以 UTC 保存，前端按本地时区显示。

### 10.1 `events`

```text
id                  bigint primary key
name                varchar(200) not null
description         text null
status              enum('draft','active','closed') not null
redemption_deadline datetime not null
pickup_location     text not null
pickup_instructions text not null
created_at          datetime not null
updated_at          datetime not null
```

### 10.2 `prizes`

```text
id                  bigint primary key
event_id            bigint not null foreign key -> events.id
name                varchar(200) not null
image               text not null
real_value          int unsigned not null
redeem_value        int unsigned not null
stock               int unsigned not null
description         text null
created_at          datetime not null
updated_at          datetime not null
```

- `real_value` 以人民币分保存，例如 ¥299.00 保存为 `29900`。
- `redeem_value` 和 quota 使用同一整数额度单位。

### 10.3 `winners`

```text
id                  bigint primary key
event_id            bigint not null foreign key -> events.id
external_id         varchar(200) null
identity_key        varchar(255) not null
name                varchar(100) not null
email               varchar(320) not null
quota               int unsigned not null
created_at          datetime not null
```

唯一约束：`unique(event_id, identity_key)`。

`identity_key`：有 external_id 时为 `external:<external_id>`，否则为 `email:<normalized_email>`。

### 10.4 `redemption_codes`

```text
id                  bigint primary key
event_id            bigint not null foreign key -> events.id
winner_id           bigint not null unique foreign key -> winners.id
code                varchar(32) not null unique
quota               int unsigned not null
status              enum('issued','redeemed','disabled') not null
redeemed_at         datetime null
created_at          datetime not null
updated_at          datetime not null
```

本轻量版允许保存兑换码明文，以便发码和管理员查看；普通应用日志不得记录完整兑换码。

兑换码固定为 12 位，使用密码学安全随机数生成器和以下字符集：

```text
ABCDEFGHJKLMNPQRSTUVWXYZ23456789
```

### 10.5 `redemptions`

```text
id                  bigint primary key
order_no            varchar(24) not null unique
event_id            bigint not null foreign key -> events.id
code_id             bigint not null unique foreign key -> redemption_codes.id
contact_name        varchar(100) not null
contact_phone       varchar(30) not null
note                varchar(500) null
total_redeem_value  int unsigned not null
quota_snapshot      int unsigned not null
pickup_location_snapshot     text not null
pickup_instructions_snapshot text not null
status              enum('submitted','ready','picked_up','cancelled') not null
created_at          datetime not null
updated_at          datetime not null
picked_up_at        datetime null
cancelled_at        datetime null
```

### 10.6 `redemption_items`

```text
id                         bigint primary key
redemption_id              bigint not null foreign key -> redemptions.id
prize_id                   bigint not null foreign key -> prizes.id
prize_name_snapshot        varchar(200) not null
prize_image_snapshot       text not null
real_value_snapshot        int unsigned not null
redeem_value_snapshot      int unsigned not null
quantity                   int unsigned not null
line_redeem_value          int unsigned not null
```

唯一约束：`unique(redemption_id, prize_id)`。

### 10.7 `notification_templates`

```text
id                  bigint primary key
event_type          varchar(50) not null unique
text_template       text not null
updated_at          datetime not null
```

### 10.8 `notification_jobs`

```text
id                  bigint primary key
event_type          varchar(50) not null
channel             enum('email','webhook') not null
winner_id           bigint null foreign key -> winners.id
redemption_id       bigint null foreign key -> redemptions.id
destination         text not null
text_rendered       text not null
status              enum('pending','sending','retrying','sent','failed') not null
attempt_count       int unsigned not null default 0
next_attempt_at     datetime null
last_error          text null
sent_at             datetime null
created_at          datetime not null
updated_at          datetime not null
```

任务创建时保存渲染后的文本；之后修改模板不影响已有任务。

## 11. API 规格

统一返回 JSON。错误格式：

```json
{
  "error": {
    "code": "machine_readable_code",
    "message": "给用户看的中文说明",
    "details": {}
  }
}
```

### 11.1 管理员密码检查

```text
GET    /api/admin/check
```

所有管理员接口（包括 `check`）都读取 `X-Admin-Password`。该接口只用于密码入口确认密码是否正确，不创建任何登录状态。

### 11.2 比赛

```text
GET    /api/admin/events
POST   /api/admin/events
GET    /api/admin/events/{event_id}
PUT    /api/admin/events/{event_id}
```

### 11.3 奖品

```text
GET    /api/admin/events/{event_id}/prizes
POST   /api/admin/events/{event_id}/prizes
GET    /api/admin/prizes/{prize_id}
PUT    /api/admin/prizes/{prize_id}
DELETE /api/admin/prizes/{prize_id}
POST   /api/admin/uploads/prize-image
GET    /api/admin/events/{event_id}/prizes/import/template?format=csv|xlsx
POST   /api/admin/events/{event_id}/prizes/import/validate
POST   /api/admin/events/{event_id}/prizes/import/confirm
GET    /api/admin/events/{event_id}/prizes/export?format=csv|xlsx
```

- 创建和编辑奖品使用 JSON；外链图片直接写入 `image`。
- 上传接口接收 multipart 文件，成功后返回站内图片 URL，再把该 URL 写入奖品的 `image`。
- 已被兑换记录引用的奖品删除时返回 409。

### 11.4 获奖人导入

```text
POST   /api/admin/events/{event_id}/winners/import/validate
POST   /api/admin/events/{event_id}/winners/import/confirm
GET    /api/admin/events/{event_id}/winners/import/template?format=csv|xlsx
GET    /api/admin/events/{event_id}/winners
GET    /api/admin/events/{event_id}/winners/export?format=csv|xlsx
```

- `validate` 接收 multipart CSV/XLSX，返回规范化预览、人数、quota 合计和逐行错误，不在服务器保存文件或创建导入会话。
- `confirm` 由前端再次上传同一个文件；后端重新解析、重新校验并在单一事务中导入。
- 奖品导入的 `validate` 与 `confirm` 使用相同的无状态模式。

### 11.5 兑换记录

```text
GET    /api/admin/events/{event_id}/redemptions
GET    /api/admin/redemptions/{redemption_id}
GET    /api/admin/events/{event_id}/redemptions/export?format=csv|xlsx
POST   /api/admin/redemptions/{redemption_id}/ready
POST   /api/admin/redemptions/{redemption_id}/pickup
POST   /api/admin/redemptions/{redemption_id}/cancel
```

### 11.6 通知

```text
GET    /api/admin/notification-templates
PUT    /api/admin/notification-templates/{event_type}
GET    /api/admin/notification-jobs
POST   /api/admin/notification-jobs/{job_id}/retry
POST   /api/admin/notifications/test-email
POST   /api/admin/notifications/test-webhook
```

### 11.7 公开兑换

```text
POST   /api/public/code/verify
GET    /api/public/redemption/context
GET    /api/public/redemption/prizes
POST   /api/public/redemptions
```

上述四个接口都读取 `X-Redemption-Code`；不创建 Cookie 或服务器会话。`verify` 仅验证并返回最小比赛摘要。

提交请求：

```json
{
  "contact_name": "张三",
  "contact_phone": "13800138000",
  "note": "下午领取",
  "items": [
    {"prize_id": 12, "quantity": 1},
    {"prize_id": 15, "quantity": 2}
  ]
}
```

## 12. 兑换提交与取消事务

`POST /api/public/redemptions` 必须在一个短数据库事务中：

1. 根据 `X-Redemption-Code` 读取并锁定兑换码行。
2. 验证兑换码为 `issued`。
3. 验证比赛为 `active` 且未超过截止时间。
4. 验证购物篮非空、没有重复 prize ID、数量均为正整数。
5. 按 prize ID 排序后锁定涉及的奖品行。
6. 验证奖品属于当前比赛且库存足够。
7. 使用数据库中的 `redeem_value` 重新计算总抵扣额度，不信任前端金额。
8. 验证总抵扣额度不超过兑换码 quota。
9. 创建兑换记录和奖品快照明细。
10. 扣减各奖品库存。
11. 将兑换码改为 `redeemed`。
12. 创建 `redemption_submitted` Email 和 Webhook 通知任务。
13. 提交事务。

任一步失败都必须全部回滚。

取消兑换也必须在一个事务中锁定兑换记录、兑换码和相关奖品，恢复库存、恢复兑换码并创建两条通知任务。

## 13. 通知 worker

实现一个独立 worker：

```text
python -m app.worker
```

处理流程：

1. 从 `notification_jobs` 领取少量到期的 `pending` 或 `retrying` 任务。
2. 领取任务时避免同一任务被重复处理。
3. `email` 任务通过 SMTP 把 `text_rendered` 作为纯文本正文发往 `destination`。
4. `webhook` 任务向 `destination` POST 第 7.2 节定义的 JSON。
5. 成功后改为 `sent`。
6. 失败后记录简短错误。第 1、2 次失败分别在 1 分钟、5 分钟后自动重试。
7. 第 3 次仍失败时改为 `failed`。
8. 管理员手工重试会把 `failed` 任务改为 `pending` 并清空下次执行时间。
9. worker 启动时将超过 10 分钟仍为 `sending` 的任务恢复为 `pending`。
10. 普通日志不得记录完整兑换码或 SMTP 密码。

## 14. 技术路线与实现约束

### 14.1 推荐结论

采用以下单体技术路线：

> **Vue 3 + TypeScript + Vite + shadcn-vue/Tailwind CSS 前端 + Python FastAPI API + SQLAlchemy 2 + MySQL/InnoDB + MySQL 通知任务表 + SMTP/Webhook + PM2 单机部署。**

开发、测试和生产统一使用 MySQL 8.x + InnoDB。MySQL 是业务数据的唯一事实来源；本地上传的图片文件是唯一的文件系统例外，其路径和元数据仍记录在 MySQL 中。

### 14.2 组件选择

| 层次 | 固定方案 | 用法 |
|---|---|---|
| 前端 | Vue 3 + TypeScript + Vite | 使用 Composition API、Single-File Components 和 Vue Router。 |
| 前端组件 | shadcn-vue + Tailwind CSS | 用于表格、表单、上传、弹窗、确认框和状态提示，保持后台与兑换页一致。 |
| 前端状态 | Pinia | 只保存当前页面生命周期内的管理员密码、兑换码和少量跨页面状态；不做持久化。 |
| 后端 API | Python 3.12 + FastAPI + Pydantic | 提供公开兑换 API、管理员 API、参数校验和 OpenAPI 文档。 |
| ORM 与迁移 | SQLAlchemy 2 + Alembic | 管理 MySQL 模型、事务和数据库迁移。 |
| 管理后台 | Vue 自定义页面 | 满足表格导入预览、奖品管理、兑换处理和通知重试，不使用通用后台生成器。 |
| 管理入口 | `X-Admin-Password` | 与环境变量直接比较；不建立用户、Cookie、Token 或服务器会话。 |
| 数据库 | MySQL 8.x + InnoDB | 开发、测试、生产使用同一种数据库语义；不同环境使用独立 database/schema。 |
| 异步任务 | MySQL `notification_jobs` + 独立 Python worker | 持久化 Email/Webhook 任务，支持进程重启续跑、自动重试和手工重试。 |
| Email | Python SMTP 客户端 | 把通知任务中的纯文本发送到指定邮箱。 |
| Webhook | Python HTTP 客户端 | 把同一通知文本以 JSON POST 到固定 URL。 |
| 表格 | Python CSV 标准库 + `openpyxl` | 实现 CSV/XLSX 模板、导入预览、校验和导出。 |
| 图片 | HTTPS 外链或服务器持久化目录 | 本地图片放 `UPLOAD_DIR`，数据库只保存 URL/路径；不使用对象存储。 |
| 进程管理 | PM2 | 生产环境管理 Uvicorn API 和通知 worker，负责重启和日志。 |
| Web 服务 | Nginx 或 Caddy | 提供 Vue 静态文件、反向代理 API/上传文件和 HTTPS；不由应用动态管理。 |
| 测试 | pytest + FastAPI TestClient + MySQL 测试库 | 覆盖导入、兑换事务、并发库存、状态变化和通知重试；前端执行类型检查和生产构建。 |

### 14.3 持久化边界

以下运行时业务状态必须进入 MySQL：

- 比赛、奖品字段和奖品图片路径。
- 获奖人、quota、兑换码和兑换状态。
- 兑换记录、奖品快照和联系人信息。
- 通知模板、通知任务、发送状态、重试次数和失败原因。

以下内容不进入 MySQL：

- 本地上传的图片二进制文件，保存在 `UPLOAD_DIR`。
- CSV/XLSX 导入原文件；接口无状态解析，确认导入后不保留原文件。
- Vue 构建产物、Python 源码、PM2 配置和环境变量。

`UPLOAD_DIR` 必须纳入服务器备份。备份恢复时，MySQL 与上传目录应来自同一备份时间点，避免数据库路径存在但图片文件缺失。

### 14.4 MySQL/InnoDB 约束

- 所有表使用 InnoDB 和 `utf8mb4`。
- 开发、测试、生产都使用 MySQL，不用 SQLite 替代测试事务和锁行为。
- 兑换码、获奖人身份键、订单号等字段建立数据库唯一约束。
- 真实价值使用整数分；quota、抵扣价值、数量和库存使用整数，不使用浮点计算。
- 兑换提交使用短事务和行锁；事务内完成兑换码校验、奖品锁定、库存扣减、兑换记录和通知任务创建。
- 事务内不得执行 SMTP、Webhook 或其他外部网络请求。
- SQLAlchemy 与 Alembic 统一管理模型和迁移；所有环境执行同一套迁移脚本。
- 测试使用独立测试库，禁止连接生产 database/schema。

### 14.5 轻量通知队列

- 不引入 Redis、Celery、RabbitMQ 或进程内临时任务。
- API 事务只创建 `notification_jobs`，独立 worker 负责网络发送。
- worker 重启后继续处理未完成任务。
- 默认只运行一个 worker；如果以后运行多个，领取任务必须使用 MySQL 行锁或租约避免重复处理。
- HTTP 请求不等待 Email 或 Webhook 完成。

### 14.6 表格与图片约束

- CSV 使用 Python 标准库，XLSX 使用 `openpyxl`。
- CSV 导出使用 UTF-8 BOM，保证常见表格软件正确显示中文。
- 导出文本如果以 `=`, `+`, `-`, `@` 开头，必须作为普通文本处理，防止公式注入。
- 单个导入文件最大 5 MB、最多 10,000 行；超出时拒绝并提示拆分。
- 图片只接受 JPEG、PNG、WebP，最大 5 MB，服务端根据文件内容确认 MIME。
- 图片使用随机文件名，禁止使用用户文件名拼接服务器路径。

### 14.7 仓库结构

固定使用以下结构，避免脚本自行猜测路径：

```text
PrizePass/
├── backend/
│   ├── app/
│   ├── alembic/
│   ├── alembic.ini
│   ├── requirements.txt
│   └── tests/
├── frontend/
│   ├── src/
│   ├── package.json
│   └── package-lock.json
├── dev.sh
├── deploy.sh
├── ecosystem.config.cjs
├── .env.example
└── README.md
```

- Python 虚拟环境固定在仓库根目录 `.venv/`。
- 前端构建产物固定在 `frontend/dist/`。
- Alembic 命令从 `backend/` 目录执行。
- API 健康检查固定为 `GET /api/health`，不要求管理员密码。

### 14.8 开发脚本 `dev.sh`

仓库根目录必须提供可执行的 `dev.sh`。运行：

```bash
./dev.sh
```

脚本行为：

1. 从仓库根目录加载并导出 `.env` 中的变量，缺少时提示复制 `.env.example` 并退出。
2. 检查 Python 3.12、Node.js、npm 和 MySQL 连接是否可用。
3. 首次运行时创建 `.venv` 并安装 `backend/requirements.txt`；缺少前端依赖时执行 `npm --prefix frontend install`。
4. 创建 `UPLOAD_DIR` 及其 `prizes` 子目录。
5. 从 `backend/` 执行 `alembic upgrade head`。
6. 同时启动 Uvicorn 开发服务、通知 worker 和 `npm --prefix frontend run dev`。
7. 捕获 `Ctrl+C`，干净停止三个子进程，不能遗留后台进程。
8. 任一核心进程异常退出时，脚本返回非零状态。

`dev.sh` 不安装或启动 MySQL；开发者应提前准备可连接的 MySQL 开发库。

### 14.9 部署脚本 `deploy.sh` 与 PM2

仓库根目录必须提供可执行的 `deploy.sh` 和 `ecosystem.config.cjs`。部署运行：

```bash
./deploy.sh
```

`deploy.sh` 必须：

1. 要求服务器已有 Python 3.12、Node.js、npm、PM2、MySQL，以及已配置的 Nginx/Caddy。
2. 加载并导出 `.env` 中的变量，检查数据库连接和 `UPLOAD_DIR`，失败时立即退出。
3. 创建或复用 `.venv`，安装锁定的生产 Python 依赖。
4. 执行 `npm --prefix frontend ci` 和 `npm --prefix frontend run build`。
5. 从 `backend/` 执行 `alembic upgrade head`；迁移失败时不重启服务。
6. 创建并检查上传目录写权限。
7. 执行 `pm2 startOrReload ecosystem.config.cjs --env production --update-env`。
8. 执行 `pm2 save`。
9. 检查 API 健康接口和 PM2 进程状态，失败时以非零状态结束。

`ecosystem.config.cjs` 只管理两个进程：

| PM2 进程 | 命令 | 实例数 |
|---|---|---|
| `prizepass-api` | 根目录 `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port ${APP_PORT}`，工作目录为 `backend/` | 1 |
| `prizepass-worker` | 根目录 `.venv/bin/python -m app.worker`，工作目录为 `backend/` | 1 |

- PM2 日志输出到部署目录下的 `logs/`。
- Vue 构建产物由 Nginx/Caddy 直接提供，不作为 PM2 进程运行。
- Nginx/Caddy 将 `/api/` 反向代理到 Uvicorn，将 `/uploads/` 映射到 `UPLOAD_DIR`，其余路径使用 Vue SPA fallback。
- `deploy.sh` 不执行 `git pull`、不创建数据库、不修改 Nginx/Caddy 配置，也不删除上传文件。

### 14.10 环境变量

```text
DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/prizepass
ADMIN_PASSWORD=
PUBLIC_BASE_URL=http://localhost:5173
APP_PORT=8000
UPLOAD_DIR=/var/lib/prizepass/uploads

SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
SMTP_FROM_NAME=PrizePass
SMTP_USE_TLS=true

NOTIFICATION_EMAIL=
WEBHOOK_URL=
```

仓库必须提供 `.env.example`，不得提交真实密码。

### 14.11 初期不引入的组件

- Docker、Docker Compose 和 Kubernetes。
- React、Next.js、Nuxt 或其他额外前端框架。
- Redis、Celery、RabbitMQ、Kafka。
- 微服务、独立 API 网关、Elasticsearch 和复杂监控平台。
- S3 或其他对象存储。
- 多 worker、多应用服务器和水平扩展。

### 14.12 升级边界

只有出现下列情况时再扩展技术架构：

- 单个 worker 无法及时处理通知任务时，再考虑增加 worker 或专用队列。
- 上传图片规模不适合本地磁盘时，再迁移到对象存储。
- 需要多台应用服务器时，再处理共享图片、分布式任务领取和负载均衡。
- 数据规模和查询复杂度确实超过 MySQL 单体能力时，再评估新的存储或分析组件。

当前轻量需求使用 MySQL 单体、一个 API 进程和一个 worker 足够。

## 15. 验收场景

### AC-01 管理员密码入口

携带正确 `X-Admin-Password` 可以访问管理员接口；缺失或错误时返回 401；全过程不创建 Cookie、Token、服务器会话或用户记录。

### AC-02 比赛

管理员可以创建含单一自提地点和截止时间的比赛，并将其从 `draft` 改为 `active`。

### AC-03 奖品六字段

管理员可以使用名字、图片、真实价值、抵扣价值、库存和描述创建及编辑奖品；接口不要求任何其他业务字段。

### AC-04 图片外链

管理员可以保存一个 HTTPS 图片 URL，兑换页面能正确显示该图片。

### AC-05 图片上传

合法 JPEG、PNG、WebP 上传成功并可访问；超出 5 MB 或非法内容被拒绝；PM2 重启和再次部署后图片仍存在。

### AC-06 获奖人表格全部拒绝

任意一行邮箱非法、quota 非整数或身份重复时，本次不新增获奖人、兑换码或通知任务。

### AC-07 导入和发码

导入 quota 分别为 100、300、500 的三人后，新增三名获奖人、三个唯一兑换码、三个 Email 任务和三个 Webhook 任务，quota 对应正确。

### AC-08 重复导入

再次导入相同 external_id 或身份 email 时失败，不新增兑换码和通知任务。

### AC-09 Email 与 Webhook 同文

同一事件产生的 Email 正文与 Webhook `text` 完全相同；某一渠道失败不影响另一渠道。

### AC-10 通知重试

发送失败后按 1 分钟和 5 分钟重试；第三次失败进入 `failed`；管理员可以手工重新排队。

### AC-11 多奖品兑换

quota 500 的码选择抵扣价值 200 × 1 和 100 × 2，总消耗 400，可以成功提交并生成两条明细。

### AC-12 超 quota

quota 500 的码提交总抵扣 501 时返回 409，不创建兑换、不扣库存、不改变兑换码。

### AC-13 库存不足

库存为 1 时请求数量 2，返回 409，所有业务数据不变。

### AC-14 单次兑换与并发

两个请求同时使用同一码提交，只有一个成功，另一个返回 409，库存只扣一次。

### AC-15 取消恢复

取消 `submitted` 或 `ready` 兑换后，库存恢复、兑换码回到 `issued`，并创建取消通知任务。

### AC-16 领取终态

`ready` 可以变为 `picked_up`；`picked_up` 不能取消或重复领取。

### AC-17 截止和关闭

比赛关闭或超过截止时间时，即使兑换码为 `issued` 也不能开始或提交兑换。

### AC-18 历史快照

提交兑换后再修改奖品的名字、图片、真实价值或抵扣价值，既有兑换明细仍展示提交时的数据。

### AC-19 奖品表格导入

同一份有效数据分别通过 CSV 和 XLSX 导入时得到一致结果；任意行非法时均全量拒绝，不新增部分奖品。

### AC-20 原始数据导出

奖品、获奖人和兑换记录均可导出 CSV 与 XLSX；字段、行数和中文内容正确；多奖品兑换按明细展开且兑换单公共信息一致。

### AC-21 无兑换会话

公开接口读取 `X-Redemption-Code`；缺失或错误时拒绝请求；验证和提交全过程不创建 Cookie 或服务器会话。

### AC-22 开发脚本

在依赖和 `.env` 正确的机器上执行 `./dev.sh`，能完成迁移并启动 API、通知 worker 和 Vite；按 `Ctrl+C` 后三个进程全部停止。

### AC-23 PM2 部署

执行 `./deploy.sh` 后，前端构建和 Alembic 迁移成功，PM2 中 `prizepass-api` 与 `prizepass-worker` 均为 online；健康检查成功；部署过程不删除 `UPLOAD_DIR`。

## 16. 开发顺序

编码 AI 必须按顺序增量实现：

1. 项目骨架、`dev.sh`、`deploy.sh`、PM2 配置、MySQL、Alembic、上传目录和管理员密码请求头检查。
2. 比赛与六字段奖品管理，包括图片外链、上传和 CSV/XLSX 导入导出。
3. 获奖人 CSV/XLSX 校验导入、导出、兑换码和通知任务创建。
4. 兑换码验证、奖品列表、购物篮和兑换提交事务。
5. 管理员兑换处理、取消恢复和领取状态。
6. Email/Webhook 适配器、统一 worker、模板和重试页面。
7. 完成全部测试、README 和端到端验证。

每一步完成后运行现有测试，不得通过重写已完成模块重新开始。

## 17. 最终交付标准

- `./dev.sh` 能启动完整开发环境中的 API、worker 和前端。
- `./deploy.sh` 能完成生产构建、迁移并通过 PM2 启动或重载服务。
- 仓库中不包含 Dockerfile、Compose 文件或 Docker 运行要求。
- 提供 `.env.example` 和本地启动说明。
- Alembic 能从空数据库创建全部表。
- 上传图片使用 `UPLOAD_DIR`，PM2 重启和重新部署后不丢失。
- 提供开发种子命令创建一场比赛和三个奖品。
- 后端测试全部通过。
- 前端 TypeScript 检查和生产构建通过。
- AC-01 至 AC-23 均有自动化测试或 README 中的可复现验证步骤。
- 所有页面连接真实 API，没有硬编码 mock 数据。
- 所有按钮均有真实功能，不存在占位菜单或 `Coming Soon`。
- 实现中没有加入本文档明确排除的能力。

## 18. 给编码 AI 的执行指令

请严格基于本文档实现完整应用。编码前先输出：

1. 固定业务规则摘要。
2. 按第 16 节拆分的实施清单。
3. 数据表和主要 API 清单。

然后从第一阶段开始增量实现。每完成一个阶段，运行相关测试并修复失败，再继续下一阶段。不得把需求替换成静态演示页面，不得使用 mock 数据冒充后端，不得增加多管理员、RBAC、报表、审计、多自提点、复杂库存、余额账户、商品抓取或其他未要求功能。
