# inv-target-check

离线检查 Sphinx `objects.inv` 中导出的每个目标是否存在于实际 HTML 发布目录。
它可以发现缺失页面、丢失锚点、路径大小写错误和越界路径，不需要运行 `conf.py` 或访问网络。

Python 3.11+，无运行依赖：

```sh
python -m pip install .
python examples/make_demo.py demo-good
inv-target-check demo-good/objects.inv demo-good
python examples/make_demo.py demo-bad --broken
inv-target-check demo-bad/objects.inv demo-bad --json
```

第一个检查返回 0；故意损坏的第二个检查返回 1。输入损坏或用法错误返回 2。
支持 `$` 对象名替换、带空格的对象名、dirhtml 空路径、百分号编码和 HTML 旧式命名锚点。
远程目标默认视为未验证并失败；`--allow-external` 仅允许这类未验证项，不会隐藏本地错误。
根相对或同站绝对 URL 需要 `--base-url https://docs.example.com/project/` 映射。

仅支持 v2 库存与 UTF-8 HTML，不模拟 HTTP 重写、重定向、动态锚点或浏览器行为。
构建成功也可能导出未生成的可选索引或 singlehtml 目标，本工具会如实报告。
库存最多 16 MiB，展开最多 64 MiB，HTML 每份最多 8 MiB；完整限制见英文 README。

通过 `python -m pip uninstall inv-target-check` 卸载；可删除自己生成的 demo 目录。
测试命令为 `python -m unittest discover -s tests -v`；真实 Sphinx 集成需要安装开发依赖。
