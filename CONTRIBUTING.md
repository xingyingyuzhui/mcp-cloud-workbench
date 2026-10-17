# 维护约定

- 本仓库维护可配置的编排与适配代码；本机地址、凭据、应用运行状态和构建产物放在忽略的 `runtime/`。
- 初始版本后使用功能分支、PR 和独立代码审查；验证后合并。仓库测试不应访问维护者的真实云资源或唤醒 GUI。
- 测试用临时目录与模拟进程；SDK 安装、真实构建、模拟器交互、SSH 配置与部署属于另行选择的集成验证。
- 修改配置 schema 时，同时更新生成器、消费脚本、模板和说明。更改存储/任务回收逻辑要覆盖活动任务、下载锁、失败工作区和有界历史。
- 不在文档中写“已验证”的新主机部署步骤，除非真的完成。每次保留运行环境、执行范围、结果及未执行内容。

本地检查：

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
python3 scripts/check_public_tree.py
find cloud -name '*.sh' -exec bash -n {} \;
```

发布前还应使用独立秘密扫描工具审核暂存文件。本仓库的 `check_public_tree.py` 只是针对常见误提交的基础检查，不能证明任意文本都不含凭据。
