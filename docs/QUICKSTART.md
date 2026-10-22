# 本地启动与测试

## 环境

历史实测环境是 Windows、Python 3.13.5、Node.js 24.19.0。新机器需要安装 Python、Node.js（含 npm）和依赖。本指南使用仓库相对路径，未包含任何个人电脑路径或认证信息。无需 Docker。

## 1. 创建 Python 环境

在仓库根目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
Copy-Item backend/.env.example backend/.env
notepad backend/.env
```

仅在本地把 `LLM_API_KEY=` 填为自己的有效 Key，确认模型名称与账号权限匹配。模板保留历史使用的 GLM Base URL 和模型名称，不保证其他账号也有同样权限。Base URL 不要再拼 `/chat/completions`，不要把 Key 放入前端或 URL。

## 2. 启动后端

从仓库根目录：

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

保持这个终端运行，使用单 worker。默认数据库是 `backend/storage/copilot.sqlite3`，首次请求/启动时初始化；工单会保存到该文件。模板与源码不包含真实 Key 或已有工单。修改私有配置后停止并重启后端。

## 3. 启动前端

新开 PowerShell，从仓库根目录运行：

```powershell
cd frontend
npm ci
npm run build
npm run start -- --hostname 127.0.0.1 --port 3000
```

开发页面也可运行 `npm run dev`。默认请求后端 `http://localhost:8000`。网页地址见根目录 README。

## 4. 工程测试（不调用模型）

从仓库根目录：

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

测试使用临时数据库和模型替身，不污染正常演示库，也不应计入模型回答准确率。前端检查在 frontend 下运行 `npm run lint` 和 `npm run build`。

## 5. 真实模型回归

在 backend 目录、已经配置有效私有 Key 后：

```powershell
..\.venv\Scripts\python.exe -m evals.run --label local-sprint2 --service --output ./eval-results/local-sprint2-001
```

输出目录必须是新目录，不能覆盖旧证据。该命令真实调用模型并产生服务商用量，记录为 `evaluation` 来源；可在 Dashboard 切换“评测数据”查看新记录。不要在评测运行中重启后端，以免启动恢复把正在评测的请求标为中断。

关键重复可加 `--split acceptance --repeat 3`。不加 `--service` 则直接运行图，不写运营数据库。

## 常见边界

- 401：在本地检查 Key、服务商和账号权限，修改后重启；不要把真实 Key 发到 issue。
- 端口占用：先停止自己之前启动的同项目服务。
- 无数据：新数据库为空，需要自己提交演示咨询。仓库中的历史 JSON 和截图不会导入数据库。
- 订单查询：使用 ORD-001、ORD-002、ORD-003；未知订单返回查无记录。它们都是演示数据。
- 移动或备份：停止后端后保留并复制数据库文件。删除数据库将丢失本机工单。私有 `.env` 也应仅保留在自己电脑上。
- macOS/Linux：环境中的 Python 路径改用 `.venv/bin/python`，前端命令不变；未把这些平台标为已实测。
