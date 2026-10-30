# 14 — 网页只保留三家 API Key 入口

**What to build:** 用户指出原有环境配置与本机 GPT 登录重复，要求 GPT 改为 API Key。网页统一只提供 Claude（CC）、GPT、DeepSeek 的 API Key 入口，当前状态、测试与实际生成均使用对应密钥。

**Blocked by:** 13 — 绑定并切换 CC、GPT、DeepSeek API。

**Status:** in-progress

- [ ] 设置中只有三家 API Key 选项，去掉本机登录和原有环境配置的选项及说明。
- [ ] 旧的本机登录或环境选择在网页中归到 GPT API Key；没有 GPT 密钥时明确提示配置，生成不隐式使用本机登录。
- [ ] 已保存的三家密钥和模型保持可用，切换、测试、删除正常；删除当前项后仍停留 API Key 模式。
- [ ] 原有 CLI 的环境变量与 Codex 适配保留，网页与 CLI 的区别在说明中写清楚。
- [ ] 聚焦验证并完成审查，空闲时更新本地网页服务，不进行真实付费推理。
