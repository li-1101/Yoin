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

确认没有生成任务后正常停止旧服务，更新后的本地服务已启动在 `http://127.0.0.1:8787`。
首页包含模型设置入口；页面、JS、CSS、配置状态和 bootstrap 均返回 200，私有配置路径返回 404。
初次上线时继续使用原有环境配置（本机 Codex 已登录）；本轮未绑定、替换或删除用户真实密钥。

## Standards

`git diff c3a613e...7703ac2` 独立规范审查通过，未关闭发现 0；三项针对性复核通过。

## Spec

相同基准独立规格审查通过，发现 0；四项针对性复核通过。未发现超出当前授权范围的功能。

Standards 0，Spec 0；两轴均无阻塞问题。

## 网页 API 入口调整

用户随后要求 GPT 登录改为 API Key，并指出本机登录与原有环境入口重复。
网页现在只提供 Claude（CC）、GPT、DeepSeek 三家 API Key，历史登录选择在网页映射为 GPT。
没有 GPT 密钥时明确提示配置，网页生成、微调与测试不调用本机登录或环境兜底；CLI 历史兼容保留。
已有三家配置保留；删除当前配置后仍在 API Key 模式。

本次配置与网页 22 项聚焦测试通过，JS 语法、DOM 三个选项和固定引用、Git 空白检查通过。
`git diff a603f0f...5ac829c` 独立复审：Standards 0、Spec 0；三项规格复核通过。
未使用真实密钥或调用付费模型。
确认服务空闲后完成更新；实际首页只有三个 API Key 选项，配置状态和 bootstrap 与 API 模式一致。

## 显式开启的本机订阅测试

日期：2026-10-31。用户授权给本人本机网页增加订阅测试入口。

- 新增 `python -m yoin.web --local-codex`，仅带此参数的进程提供并默认使用本机 Codex。
- 本机订阅选择只存在于服务进程中，不写入连接配置、不修改 CLI 已保存的 API 选择。
- 普通启动在后端拒绝 Codex 选择与检查；旧配置、环境变量及请求参数不能开启此能力。
- 缺少本机登录时明确报错，不回退到已保存的 API 或环境配置。
- 支持切换已配置的 API 和本机 Codex。生成开始时固定入口，切换只影响下一次生成或微调。
- 继续只监听 `127.0.0.1`，本机入口沿用 Host、Origin 与会话 token 校验。
- 「检查本机登录」只检查官方 CLI 登录状态，不执行模型请求。没有读取或复制认证文件。

`python -m unittest tests.test_web tests.test_connections tests.test_codex_model -v`：32 项通过，耗时 42.845 秒。
覆盖默认拒绝、显式启动、进程间隔离、配置不持久化、缺少登录不兜底、HTTP 生成与两种入口的微调、运行中切换、请求参数及来源校验。
这些模型调用使用临时项目、脚本模型和本机模拟 HTTP 服务，没有使用真实订阅或付费 API 推理。
JS 语法与 Git 空白检查通过。

确认当前服务没有生成任务后，用显式参数重启 `http://127.0.0.1:8787`。
Safari 已显示「本机 Codex · 订阅测试 · 已登录」，生成及微调按钮可用，模型设置弹窗只显示本机入口说明和对应操作。
通过页面点击「检查本机登录」得到成功反馈，未发送真实模型生成请求。
这只验证登录与接线，不代表订阅剩余额度、具体可用模型或真实声音效果已经验收。

此进程仅用于本人本机测试，不作为反向代理或隧道后的共享服务；回环地址也不替代同一电脑上的多用户身份认证。
分享代码或正常部署不携带个人 Codex 凭据，部署时不启用该参数。
参考 [官方认证说明](https://learn.chatgpt.com/docs/auth) 与 [非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)。

## 参考

接口及默认名称以官方文档核对：

- [OpenAI Chat Completions](https://developers.openai.com/api/reference/chat-completions/overview)
- [GPT-5 Mini](https://developers.openai.com/api/docs/models/gpt-5-mini)
- [Claude Messages](https://platform.claude.com/docs/en/api/messages/create)
- [Claude Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/overview)
- [DeepSeek First API Call](https://api-docs.deepseek.com/en/)
- [DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)
