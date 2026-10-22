> 公开整理版：保留原始结论与实测数字，移除了个人路径和机器专用步骤。报告中的本地归档文件未全部收录，公开材料以评测索引为准。

# AI Customer Service Copilot MVP 技术可行性分析

日期：2026-10-17｜周期：约两周，按 10 个工作日规划｜形态：单店、本机演示

## 结论与范围

**可行。保留 FastAPI、LangGraph、Next.js 和现有 Provider，新增一个 SQLite 数据文件及少量业务接口即可。** 工作重点是客服事实可靠、工单可跟进、运营数据可追溯、评测结果可复核，而不是扩充 Agent 数量。

本分析已核对现有代码和 `PROJECT_AUDIT.md`。环境故障及更换密钥问题已解决；用户已体验商品、订单、物流、投诉及退款相关场景。**体验过场景不代表已有退款执行能力**：代码仍只有政策查询、只读订单/物流工具和临时工单对象，没有持久化工单、Dashboard 或质量评测系统。

两周目标：保留买家聊天入口，增加商家工单页和运营概览，并用固定评测集展示改进前后差异。“Copilot”指帮助商家回复和跟进，退款、赔付和工单结案仍由人决策。暂不做多租户、真实平台对接、自动退款、复杂权限、长期对话记忆或公网 SaaS。

本文全部新增设计均为建议，尚未实现。本次只编写文档，没有读取密钥配置、调用模型或修改业务代码。

## 1. 哪些模块可以复用

| 原有模块 | 复用判断 | 必要调整 |
|---|---|---|
| `agents/graph.py` 的 Router → 分支 → Summary | 保留工作流及节点划分 | 不增加新 Agent；补状态字段，保持原路由结构 |
| `data/base.py`、`demo_provider.py` | 直接复用数据接口和演示订单/商品/物流 | 统一存在冲突的政策口径；评测冻结数据和日期 |
| `tool_agent.py` 的四个查询执行函数 | 复用只读查询逻辑 | 参数校验、缺参数追问、结构化执行结果；不增加资金操作 |
| FastAPI 与 Pydantic | 直接复用 API 和校验基础 | 增加工单、统计接口及请求标识；统一错误格式 |
| `llm_client.py` 的兼容接口调用 | 复用网络调用方式 | 增加调用耗时、用量和错误类型采集；不保存认证信息 |
| Next.js 聊天页、请求封装和工单卡片 | 直接复用 UI 基础 | 增加工单状态、来源、错误恢复和商家导航 |
| `vector_store.py` | 保留接口，不能原样依赖其检索质量 | 补商品编号/名称匹配、列表查询和无命中处理；先不引入向量数据库 |
| SSE、CLI、Docker 配置 | 保留现有入口 | 网页继续用普通 JSON；SSE 不包装成实时推理；Docker 修复不作为本轮关键路径 |

建议只加一层轻量 `chat_service.run_chat()`，让 HTTP、SSE、CLI 共享“执行工作流 → 保存结果/工单 → 返回响应”。SQLite Repository 专管存储，Provider 继续专管电商查询，避免把二者混成一个大型数据层。

## 2. SQLite 是否适合工单持久化

**适合本轮的单机、单店、少量并发写入和频繁读取场景。** 使用 Python 标准库 `sqlite3`，不新增数据库服务、ORM 或消息队列。SQLite 官方也将本地存储、数据分析和演示测试列为适用场景；大量并发写入、多服务器共享存储才需要重新评估数据库。[官方适用场景](https://www.sqlite.org/whentouse.html)

建议将文件放在后端独立的 `storage/copilot.sqlite3`，路径按项目目录解析，加入 Git 忽略。开发阶段运行单个后端 worker；每个操作单独获取连接、使用参数化 SQL、开启外键和有限锁等待。**调用模型时不持有数据库事务**，只在落库时开启短事务。

先用默认日志模式即可；若后续实测读写等待明显，再评估 WAL。WAL 可以改善读写并行，但仍只有一个写者，数据库文件应保存在同一台机器的本地磁盘上。[官方 WAL 说明](https://www.sqlite.org/wal.html)

### 最小工单模型与状态

工单字段：`ticket_id`（程序生成 UUID）、`source_request_id`（唯一）、`conversation_id`、可空 `order_id`、`summary`、`category`、`detail`、`urgency`、`status`、`resolution_note`、`created_at`、`updated_at`、可空 `resolved_at`、`version`。

状态只保留三个：`open（待处理） → in_progress（处理中） → resolved（已处理）`。允许 `resolved → in_progress` 重新处理并填写原因；拒绝非法状态转换，处理完成必须填写说明。`resolved` 只是商家标记工单处理完成，不能解释成“退款已到账”。

- 工单当前状态放 `tickets`，变更历史放 `events`；更新二者必须同一事务提交。
- 使用 `version` 检查并发修改，过期更新返回 409，避免两个页面互相覆盖。
- 同一 `request_id` 的重试复用已有结果；处理中的重复请求返回处理中，不能再执行一次图。前端只有主动发起新问题才生成新 ID。
- 投诉节点只生成经过校验的草稿；服务层分配编号并落库后，再用确定性模板回复“已记录，等待商家处理”。写入失败必须明确失败，不能返回“工单已保存”。
- 服务启动时将异常退出遗留的 `processing` 请求标成 `interrupted`；已提交结果可重复获取。正常重启、刷新后工单仍可查询。
- 数据库备份、迁移前先停止服务或使用数据库备份接口；不把正在写入的文件当普通文件随意复制。

## 3. 运营分析需要的最小事件和字段

不接入独立埋点平台。建议仅建三张表：`chat_turns`（请求与回复）、`tickets`（工单当前状态）、`events`（结构化操作记录）。会话先用 `conversation_id` 关联，不额外建用户系统。

### 业务事件

| 事件 | 何时记录 | 专属最小字段 |
|---|---|---|
| `chat_received` | 后端接受有效请求时 | `request_id`、`conversation_id`、脱敏问题、`channel` |
| `chat_finished` | 成功或失败的终态 | `execution_status`、`intent`、`answer_type`、`reason_code`、`latency_ms`、脱敏回复/错误码 |
| `tool_executed` | 每次工具执行结束 | `call_id`、工具名、必要参数摘要、`result_status=found/not_found/invalid/error`、耗时 |
| `ticket_created` | 工单事务提交时 | `ticket_id`、类别、紧急程度、初始状态 |
| `ticket_status_changed` | 合法状态更新提交时 | `ticket_id`、旧/新状态、处理说明、操作人（演示固定为 merchant） |
| `feedback_recorded`（可后置） | 用户明确反馈已解决/未解决时 | `request_id`、`resolved=true/false`；同一请求更新反馈，不能重复计数 |

事件通用字段：`event_id`、`event_type`、`occurred_at`、`request_id`、`conversation_id`、`data_source`。工单关联事件附 `ticket_id`；按事件类型和业务键设唯一约束，避免重试重复记数。

`chat_turns` 另外保留 `model_name`、`prompt_version`、`knowledge_version`、检索来源 ID、工具结果状态；用量字段为可空 `prompt_tokens`、`completion_tokens`。每次实际模型调用的耗时、状态、用量可放该请求的 `llm_calls_json`，无需再建调用平台。当前客户端只返回 message，**必须扩展采集才能获得 usage，不能直接声称已统计成本**；未知用量留空，不记为 0。

`answer_type` 由可观测结果设置为 `grounded_answer/clarification/unsupported/handoff_recorded/error`，不让模型凭感觉声明“客户问题已解决”。请求执行状态另用 `processing/succeeded/failed/interrupted`。

时间统一按 UTC 保存，Dashboard 按 Asia/Hong_Kong 切日。`data_source=demo/evaluation` 分开过滤，评测流量和预置展示数据不混入商家使用指标；接口重试按 request_id 去重。只保存演示数据或脱敏文本，不保存请求认证头和敏感配置。

### Dashboard 首版只做五组可核验结果

| 指标 | 口径 |
|---|---|
| 咨询量、独立会话数 | 所选日期内唯一 request_id / conversation_id；不能写成独立客户人数 |
| 意图分布 | 所选请求的最终意图；失败未分类单列 unknown，分母不暗中缩小 |
| 工单状态分布、待处理明细 | 显示筛选期间新建工单的当前状态；另外明确显示全量当前待处理数，避免时间口径混淆 |
| 请求失败率、响应耗时 | failed/interrupted ÷ 已到终态请求；processing 单列；成功/失败耗时分开展示并显示样本数 |
| 未直接回答原因与问题明细 | 按 missing_order_id、not_found、no_evidence、complaint 等确定性 reason_code 汇总，能点击查看原始请求 |

反馈功能如有余量再做；届时“未解决反馈占比”只在已反馈样本内计算，同时展示反馈覆盖率。没有反馈就不展示解决率、满意度或人工节省率。自动生成文字不等于问题解决；问题列表也不等于已完成语义聚类。

## 4. 必须先修复的 Agent 问题

| 优先级 | 现有依据 | 最小修复与验收重点 |
|---|---|---|
| P0 | Escalation 秒级编号；Summary 没收到真实编号却声称已转人工 | 程序生成唯一 ID、落库后模板确认；正文、卡片、列表编号一致；模型只能提供受限草稿字段 |
| P0 | 商品泛问法召回失败，P001 检索零相似度也返回文档 | 商品列表走 Provider.list_products，编号/名称优先精确匹配；检索设可调门槛，无证据明确说明；门槛用开发集验证 |
| P0 | Knowledge 答案未传入 Summary；文档/工具结果被硬截断 | 将答案、来源与完整关键事实放到显式状态；知识分支可直接采用合格答案，不再重复生成；工具分支保留结构化事实 |
| P0 | 退货政策通用文档 7 天，服装结构化政策 15 天；通用质保 12 月但充电板为 6 月 | 明确商品信息优先商品记录、分类政策优先分类记录；退款政策咨询与退款申请分开，缺类别追问；不承诺退款成功 |
| P0 | JSON 直接 loads，参数缺失时传空值；工具未调用时回答没有进入汇总 | Pydantic 校验意图、工具白名单/参数、工单草稿；参数不足追问，非法输出有限兜底；工具成功、未找到、失败分开 |
| P1（本轮完成） | 普通聊天同步阻塞；SSE 异常在 200 后中断；UI 在线状态写死 | 请求执行移到线程执行路径，错误统一 reason_code/request_id；SSE 共用服务并发 error 事件；网页继续普通 JSON，改善等待/失败提示 |

暂不实现完整多轮记忆。conversation_id 用于关联和统计，**记录会话不等于模型拥有记忆**；“它多少钱”“上一单呢”等缺信息输入应明确追问，而不能猜订单。知识文档仅作为证据，不能执行其中要求越权操作的指令。

## 5. 最小质量评测集

**建议 36 条人工标注业务样本：28 条开发集 + 8 条冻结验收集。** 验收集在第一天锁定、覆盖下面七类关键场景；若根据验收失败继续调参，需明确披露，并补新样本验证，不能继续宣称它是未见测试。

| 类别 | 数量 | 必须覆盖 |
|---|---:|---|
| 商品 | 8 | 商品列表、价格、规格、P001、同义改写、不存在商品、商品特定质保 |
| 订单 | 6 | 三种状态、未知订单、缺编号、编号格式变化 |
| 物流 | 5 | 在途、待揽收、已签收订单缺物流、未知订单、缺编号 |
| 退款/政策 | 5 | 一般政策、服装 15 天、电子产品条件、退款申请待人工处理、不得承诺已退款 |
| 投诉 | 5 | 明确投诉、质量问题、要求人工、重复同一请求、不承诺已接单 |
| 模糊/越界 | 4 | 缺上下文、天气等范围外问题、复合诉求、无证据问题 |
| 诱导与冲突 | 3 | 要求编造物流、绕过退款流程、忽略商品证据中的真实价格 |
| **合计** | **36** | 不只使用 README 中的六句标准输入 |

每条标注：`case_id`、`split`、`scenario`、输入、允许的 intent/工具、期望事实或来源、允许的 answer_type、禁止承诺、是否应建工单。用事实和行为判分，不逐字匹配整段话。遇到可接受的多条路由时列出允许集合。

执行方式：真实模型跑业务样本，规则核对 ID/价格/状态/工具参数，人工复核证据充分性和承诺；不引入第二个模型当唯一裁判。保留逐题结果、模型/提示词/知识版本、耗时和失败类型。冻结物流“今天”的时间基准，避免动态预计日期让评测漂移。

另做少量**不调用模型的工程测试**：超时/401/无效 JSON、数据库写失败、重启后查询、非法状态更新、同请求去重及反馈更新。这些替身测试验证程序，不算模型效果样本。当前仓库没有已有自动化测试可直接继承。

建议验收门槛：整体场景通过至少 **33/36**；8 条关键验收用例各重复 3 次，要求工单编号一致、无虚假退款/人工接单、未知数据不编造等关键约束 **24/24** 通过。指标只是项目验收目标，不是当前已实现成绩，也不是生产质量保证。耗时报告中位数及范围，样本少时不包装成可靠 P95。

## 6. 每个功能预计改哪些文件

以下路径均相对于当前源码根目录 ``；“新增”仅表示计划，本次不会创建这些业务文件。

| MVP 功能 | 修改现有文件 | 建议新增文件 |
|---|---|---|
| 可靠问答与退款边界 | `backend/app/agents/{router_agent,knowledge_agent,tool_agent,summary_agent,escalation_agent}.py`、`backend/app/knowledge_base/vector_store.py`、`backend/app/data/demo_provider.py`、`backend/app/models/schemas.py` | 无需新 Agent |
| 统一执行、会话与事件记录 | `backend/app/main.py`、`backend/app/agents/llm_client.py`、`backend/app/models/schemas.py`、`backend/app/cli.py` | `backend/app/chat_service.py`、`backend/app/storage/{__init__,database,repository}.py`、`backend/app/storage/schema.sql` |
| 持久化工单及状态 | `backend/app/main.py`、`backend/app/agents/{escalation_agent,summary_agent}.py`、`backend/app/models/schemas.py`、`frontend/lib/{api,types}.ts`、`frontend/app/page.tsx` | `frontend/app/merchant/tickets/page.tsx`；后端复用上述 Repository |
| Dashboard | `backend/app/main.py`、`backend/app/storage/repository.py`、`frontend/lib/{api,types}.ts`、`frontend/app/layout.tsx` | `frontend/app/merchant/dashboard/page.tsx`、`frontend/app/merchant/layout.tsx`；简单卡片、表格和条形展示即可 |
| 聊天体验及标识传递 | `frontend/app/page.tsx`、`frontend/lib/{api,types}.ts` | 可抽出 `frontend/components/ChatMessage.tsx`，仅在页面明显臃肿时做 |
| 质量评测 | `backend/requirements.txt`（区分/声明测试依赖）、README | `backend/evals/cases.jsonl`、`backend/evals/run.py`、`backend/tests/test_{chat,tickets,metrics}.py` |
| 存储路径与启动说明 | `backend/app/config.py`（仅新增 DB 路径设置）、`.gitignore`、README | 本地 storage 数据目录；数据库、评测结果不提交 Git |

最小接口：保留 `POST /api/chat` 并增加 request_id/conversation_id；增加 `GET /api/tickets`、`GET /api/tickets/{id}`、`PATCH /api/tickets/{id}/status`、`GET /api/analytics/overview`、`GET /api/analytics/requests`。反馈若实施，再加 `PUT /api/chat/{request_id}/feedback`。不新建另一个后端服务。

`graph.py` 不需要重新设计；如果节点输出字段变化，只调整状态契约。订单/物流 Provider 不必迁移进 SQLite，先让数据库保存本产品产生的工单、请求和事件。

## 7. 两周开发顺序与验收标准

估算前提：现有环境继续可用、单人开发、单店演示数据、每天有连续开发时间。属于范围约束下的估算，涉及未知模型行为时需用末两天缓冲；不含真实电商平台接入。

| 时间 | 交付内容 | 当日/阶段验收 |
|---|---|---|
| D1 | 锁定范围、36 条标注、政策优先级、指标口径 | 每条样本有依据；区分退款咨询/申请/实际执行；形成未改造基线 |
| D2–D3 | 修 Agent 的 P0 问题与错误边界 | 商品列表/编号可答；无证据不编；真实工单事实不由模型补写；政策冲突用例通过 |
| D4–D5 | SQLite、统一服务、事件、持久化工单 | 创建→列表→处理中→已处理可演示；刷新和重启不丢；同请求只一张工单；写失败不报成功；状态与事件一致 |
| D6–D7 | 工单页、Dashboard、请求明细 | 由确定的演示数据逐项核对统计，重试不增量；零数据不报错；日期过滤正确；评测数据可排除 |
| D8 | 评测脚本、错误工程测试、结果报告 | 达到 33/36 和关键约束门槛；每个失败可定位到检索、工具、生成或程序；可重跑对比基线 |
| D9–D10 | 缓冲、端到端回归、UI 文字与面试材料 | 全链路演示、重启验证、数据库备份恢复；前端 build/lint/typecheck 及后端测试通过；遗留问题明确列出 |

若超时，优先删减图表美化、反馈功能和模型用量图表；保留可靠回复、工单持久化、基础统计和固定评测。不要削减事实一致性验收以换取更多页面。

最终演示建议：用户问商品/查物流 → 投诉生成真实持久化工单 → 商家更新处理状态 → Dashboard 指标与明细同步 → 展示同一评测集的改进前后结果。这样能说明产品决策、业务闭环和效果验证，而不只展示 LangGraph 节点。

### 本轮边界

默认仅本机演示，页面明确标记演示数据。不能把商家页面路径当作权限控制；若需要公网展示或真实商家数据，认证、订单归属、依赖漏洞修复和部署持久磁盘需另行纳入范围。以上计划不宣称已经完成客户验证、节省人工成本或提升销售额。
