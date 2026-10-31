# 15 — 显式开启的本机 Codex 网页订阅测试

**What to build:** 用户希望自己在本机网页通过已登录的 ChatGPT Pro 订阅测试，同时避免其他访客借用该账号。复用现有 Codex CLI 适配，仅通过启动参数 `--local-codex` 开放网页入口。

**Blocked by:** 14 — 网页 API Key 入口。

**Status:** done

- [x] 普通启动只提供 API Key；后端拒绝本机 Codex 选择和测试，不从登录或环境变量兜底。
- [x] 显式开关启用并默认选择本机 Codex；选择仅在当前进程生效，不写入项目配置。
- [x] 网页支持切换 API Key 与本机 Codex、检查本机登录；检查不发模型请求，生成与微调使用选定入口。
- [x] 保持只监听回环地址，沿用 Host、Origin 和会话 token 校验，不读取或复制 Codex 认证文件。
- [x] 验证普通启动、启用后生成与微调、进程间隔离、缺少登录、API 切换与请求期间的选择固定。
- [x] 更新启动说明并打开本机网页验证。

验收：网页、配置与 Codex 适配共 32 项测试通过；JS 语法、DOM 引用和 Git 空白检查通过。
本机网页已用显式开关启动，Safari 页面显示已登录并通过本机登录检查。未执行真实模型生成。
记录见 `docs/model-connections-validation.md` 的「显式开启的本机订阅测试」。
