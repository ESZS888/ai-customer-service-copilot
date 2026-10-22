# 上传 GitHub

## 上传内容

只上传当前 `ai-customer-service-copilot` 文件夹里面的 backend、frontend、docs 和根目录文件。不要上传它外面的 outputs、work、虚拟环境或依赖目录。这里已经提供空 Key 的 `.env.example`；不要再从原工作目录复制真实 `.env` 或数据库。

## 方式

推荐 Fork 原仓库到自己的账号，克隆后把本目录内容同步到 Fork 的工作区，再检查变更并提交；保留原来的 `.git` 历史。若新建独立作品集仓库，请保留 README 和 THIRD_PARTY_NOTICES 中的上游来源。

使用 GitHub 网页上传时，可分批上传 backend、frontend、docs 和根目录文件；不要把所有内容再套一层 outputs/work。确认 `.gitignore` 和 `backend/.env.example` 也被上传。GitHub 上的根目录应直接看到 README.md、backend、frontend 和 docs。

建议仓库名：`ai-customer-service-copilot`。

建议简介：面向中小电商商家的 AI 客服与运营辅助 MVP：可靠问答、SQLite 工单闭环、真实事件 Dashboard 与固定案例评测。

## 整理边界

这是独立整理版，不影响原桌面运行副本。未上传到任何账号、未新建 GitHub 仓库、未包含原 Git 历史。原有 Windows 专用机器路径脚本被通用安装说明替代。首次运行需要自己安装依赖和配置本地 Key，数据库为空。

PRD 为实际已有的 v1.0，没有伪造 v1.1、Figma 链接、线上演示地址或用户研究。Word 原稿保留在原产品资料文件夹，GitHub 采用可直接阅读的 Markdown 版本。
