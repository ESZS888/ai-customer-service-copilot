# 固定业务评测

`cases.jsonl` 为 36 条冻结业务案例，`score.py` 为固定规则评分器。历史结果和局限见 [公开评测索引](../../docs/evaluation/README.md)。

在 backend 目录，已配置自己的本地私有模型凭据后运行：

```powershell
..\.venv\Scripts\python.exe -m evals.run --label local-sprint2 --service --output ./eval-results/local-001
```

输出目录必须尚不存在。`--service` 使用统一执行服务并记录为 evaluation 来源；不加时直接运行图，不写运营数据库。追加 `--split acceptance --repeat 3` 可重复关键案例。评测会真实调用模型并产生服务商用量，不记录认证头。

工程测试请在 backend 运行 `..\.venv\Scripts\python.exe -m pytest -q`；这些使用模型替身和临时数据库，不记作业务模型效果。完整安装步骤见 [QUICKSTART](../../docs/QUICKSTART.md)。
