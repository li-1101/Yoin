# 多家模型入口验收

日期：2026-10-30。基准：`c3a613eac9b6672323226d89c784d4746df435ff`。
范围：本地网页的 Claude（CC）、GPT、DeepSeek API Key 入口；保留 Codex 与环境变量入口。
本轮没有实现聊天、个人记忆或公网访问。

## 自动化

- 模型配置与 Claude 原生适配共 13 项测试通过。
- 既有 agent、OpenAI 兼容接口、Codex、运行记录与网页，以及新增 HTTP 配置验证共 49 项测试通过。
- 合计 62 项：使用临时目录和本机 HTTP 模拟服务，不访问真实推理服务、不使用真实密钥。
- `node --check yoin/web_assets/app.js` 与 `git diff --check` 通过。
- HTML 62 个 ID 唯一，JS 的 52 个固定 ID 引用均有对应元素；未使用 localStorage / sessionStorage。
- 安装 Anthropic SDK 2.3.0，`pip check` 通过。

## 行为与保护

- 三家配置分别持久化，可替换、留空沿用、删除和选择；新建存储实例读取相同选择。
- 私有目录 0700、配置文件 0600，原子替换写入；并发保存保留其他家的配置。
- 配置不通过静态路由开放，读取接口没有密钥字段；所有变更与连接测试沿用本机 Host / Origin / CSRF 校验。
- URL 中的账户、密码、查询参数、片段及不合法端口会被拒绝；输入校验错误不回显秘密值。
- 配置目录、文件为符号链接时拒绝读取或写入；损坏配置以中文错误报告。
- 保存、选择、公开状态读取不发送推理请求。显式测试要求返回真实函数调用与布尔参数，普通文本或错误类型不能冒充通过。
- 网页生成实际使用选择的 API；CLI 同样读取已选入口。任务开始时固定模型和密钥，运行中替换或切换只影响下一次。
- 原生 Claude 保留 system、工具参数、连续工具结果和原生思考签名；GPT / DeepSeek 使用现有工具协议，DeepSeek 关闭思考模式。
- 原有模板、指导、混音规则、生成、微调、评分和媒体范围下载测试通过。
- 模拟认证、权限、配额、服务错误不会回显服务错误正文或密钥。

## 验收范围

没有使用真实 API Key 验证账户权限、余额或实际模型质量；用户可在设置中点击测试完成账户侧验证。
当前浏览器页面受 Computer Use 访问限制，本轮未通过浏览器操作验证弹窗视觉与交互；完成了静态检查与 HTTP 行为验证。

## 参考

接口及默认名称以官方文档核对：

- [OpenAI Chat Completions](https://developers.openai.com/api/reference/chat-completions/overview)
- [GPT-5 Mini](https://developers.openai.com/api/docs/models/gpt-5-mini)
- [Claude Messages](https://platform.claude.com/docs/en/api/messages/create)
- [Claude Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/overview)
- [DeepSeek First API Call](https://api-docs.deepseek.com/en/)
- [DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)
