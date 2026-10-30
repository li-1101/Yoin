# Yoin（余韵）

**Your Own Inner Nook**

将场景描述变成背景声音的实验。本地网页支持 Claude、GPT、DeepSeek API Key：描述场景、生成、对比初稿和终稿、文字微调、保存试听评分。

## 本地网页

先启动本地网页，再在页面里配置 API Key：

```bash
source .venv/bin/activate
python -m yoin.web
```

打开 <http://127.0.0.1:8787>。服务只监听本机；可用 `--port 8788` 更换端口，在启动服务的终端按 Ctrl-C 停止。
页面支持后台生成进度、声音足迹、两版播放和 WAV 下载、从已有版本微调，以及 1–5 分和试听备注。
初稿与终稿均为 120 秒，默认不自动播放。中断但已保存初稿的运行，也可以从初稿继续。

右上角「模型设置」支持分别绑定 **Claude（CC）、GPT、DeepSeek**：选择入口，粘贴该服务的 API Key，
填写模型名称后保存，再点击「使用此入口」。模型和服务地址已提供默认值，可自行修改。
三家的密钥互不覆盖，已保存的密钥不回填到页面；留空保存会沿用旧密钥，删除按钮可以移除整家配置。
「测试连接」会发送一条简短的工具调用请求，使用所选 API 的额度；保存和切换不会发送生成请求。
页面显示「已配置」只代表本地配置就绪，连接测试结果会另行显示。

CC 在这里指 Claude / Anthropic API 接入，不使用 Claude Code 的登录或订阅凭据。
网页只提供三家 API Key 入口，默认指向 GPT；旧的本机登录或环境选择也在网页中指向 GPT API Key。
没有对应密钥时，网页提示配置并禁用生成，不会使用本机登录或环境变量兜底。
选定入口同时用于网页生成、微调和 CLI；切换或替换密钥只影响下一次任务。
CLI 仍兼容历史环境变量与本机 Codex 入口，只有命令行会读取这些历史选择。

密钥以明文保存在本机 `.yoin/connections.json`，目录权限为 0700，文件权限为 0600。
该目录不进入 Git；读取接口、运行快照和普通错误消息均不返回密钥，浏览器不持久保存密钥。
这仍是本机单人入口，聊天、个人记忆和公网分享尚未接入。

Claude 使用原生 [Messages 与工具调用](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)；
GPT 沿用现有 [Chat Completions](https://developers.openai.com/api/reference/chat-completions/overview)，
DeepSeek 使用其 [兼容接口](https://api-docs.deepseek.com/en/)和
[非思考工具调用方式](https://api-docs.deepseek.com/guides/tool_calls/)。
默认模型为 `claude-sonnet-5-5`、`gpt-5-mini`、`deepseek-flash`，可按密钥实际可用的模型修改。

网页使用选定 API 进行推理，音频在本机渲染，音频和评分保存在项目的 `runs/` 中。
历史 CLI 使用官方 [`codex exec`](https://learn.chatgpt.com/docs/non-interactive-mode) 复用本机登录；
登录方式见 [Codex authentication](https://learn.chatgpt.com/docs/auth)。

## 安装和试听

需要 Python 3.11+。在项目目录执行：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m yoin.make_placeholders
python -m yoin.render templates/window_rain.recipe.json --seconds 30 --out runs/window-rain.wav
```

下载素材已随项目保存在 `sounds/recorded/`。按用户反馈，新试听推荐：

```bash
python -m yoin.render templates/quiet_reading.recipe.json --seconds 60 --out runs/quiet-reading.wav --analysis runs/quiet-reading.analysis.json
```

此模板只用水滴、鸟叫和翻书，去掉持续噪声和混响。当前规则目标响度为 -30 LUFS。
素材作者、许可和处理记录见 [声音来源](docs/audio-sources.md)。
另有两首 CC0 古典音乐保存在 `sounds/music/` 并已登记进声音库：巴赫《C 大调前奏曲 BWV 846》、
萨蒂《第一号吉姆诺佩蒂》。可在场景里直接说曲名，下一次生成即会加载。
四种 CC0 环境声保存在 `sounds/ambience/`：海浪拍岸、风吹树叶、篝火噼啪、夏夜虫鸣。
在场景中直接写名称即可选用；本机 30 秒单独试听位于 `runs/ambience-preview/`。
用户 `Downloads/10.28` 收集的十份素材已导入 `sounds/user_10_28/`，包含日本城市场景、鸟鸣、汽笛、钟声和海浪。
本机独立试听在 `runs/user-10-28-preview/`；来源、完整原档缓存位置、取段及许可核对状态均在该批次 `sources.json` 中。
该批十份素材已由用户确认免费且有使用许可，目录和试听页已同步记录。

生成七种占位声音不需要密钥或外部素材。占位声音是噪声、正弦和短脉冲，主要用于验证控制和流程。
`pad_soft_01` 是合成和弦，不能当作真实爵士乐。输出为 48000 Hz、双声道、32 位浮点 WAV。

默认从当前目录读取 `library.json` 与 `mixing_rules.json`。在其他目录调用时，可设置：

```bash
export YOIN_PROJECT_DIR=/path/to/yoin
```

生成的 `sounds/*.wav` 和 `runs/` 不进入 Git；生成的声音目录纳入 Git，方便后续编辑。
新 checkout 中已有标准声音目录、但尚无音频时，可以直接运行生成命令。
重新生成七种占位素材会覆盖同名占位文件，需显式使用下面命令；额外的下载素材和描述会保留：

```bash
python -m yoin.make_placeholders --force
```

可用 `--seconds 60` 生成更长的循环素材，范围为 30–60 秒。

## 场景到最终音频

同样可以直接通过命令行生成：

```bash
YOIN_PROVIDER=codex python -m yoin.run "午后安静阅读，偶尔有水滴，远处鸟叫，翻页轻一点，不要持续雨声"
```

`YOIN_PROVIDER` 支持 `codex`、`api`、`auto`（默认）。`auto` 在没有 `YOIN_API_KEY`／`YOIN_BASE_URL`／`YOIN_MODEL` 时使用本机 Codex；
出现任一 API 配置项时改用 API，并要求三项完整。Codex 可用 `YOIN_CODEX_MODEL` 指定模型，不填则沿用 CLI 默认模型。

如需支持 Chat Completions function calling 的服务，配置 API 入口：

```bash
export YOIN_API_KEY="你的服务密钥"
export YOIN_BASE_URL="https://api.example.com/v1"
export YOIN_MODEL="支持工具调用的模型名"
YOIN_PROVIDER=api python -m yoin.run "深夜写代码，窗外下着小雨，远处有一点音乐"
```

程序依次调用 `render_and_analyze` 和 `submit_recipe`，最多八轮模型请求、四次试听。
试听默认 30 秒，第一版和最终版均保存为 120 秒。收到建议后至少尝试一次参数调整，允许带建议提交。
标题、种子和层命名的改变不能替代混音参数调整；第四次试听后应提交最后已试听的配方。

如果八轮后未提交，使用最后一份成功试听的配方，明确记录 `fallback` 和“未主动提交”。
服务请求失败但已有有效试听时，也保存兜底结果。从未产生有效配方时返回中文错误并保留失败记录。
API 每次请求超时为 60 秒；Codex 默认 180 秒，可用 `YOIN_CODEX_TIMEOUT` 设置为 1–600 秒。
不自动重试模型请求。按 Ctrl-C 中断 CLI 时保留已完成的过程与试听；停止网页服务会关闭其持有的模型连接。

使用本地模型服务且机器配置了 HTTP 代理时，请为回环地址设置 `NO_PROXY`。
程序沿用系统代理设置；测试服务只在测试期间绕过回环地址代理并在退出时恢复。

工具调用消息及 `tool_call_id` 的往返遵循 [OpenAI function calling 文档](https://developers.openai.com/api/docs/guides/function-calling)。
API 服务和模型由上述环境变量指定。

## 从已有版本微调与评分

将运行编号替换为 `runs/` 下实际的目录名：

```bash
python -m yoin.run "鸟叫再远一点，翻页少一些" --from 运行编号
python -m yoin.rate 运行编号 --which final --score 4 --note "更柔和，翻页还可以少一点"
```

微调把旧配方带回模型，默认要求保留 seed、layer_id 和无关参数；用户新要求优先于模板。
每次微调另建运行目录，`inputs.json` 记录 `parent_run_id` 和 `base_recipe`，原版产物保留。
评分的 `which` 为 `draft` 或 `final`，分数是 1–5 的整数，备注可选且最多 2000 字。
`runs/ratings.jsonl` 逐条追加运行编号、版本、评分、备注、配方 SHA256、渲染器版本和当轮参考模板内容哈希。

## 测量与可编辑规则

直接渲染时可以额外保存分析：

```bash
python -m yoin.render templates/window_rain.recipe.json --seconds 30 --out runs/preview.wav --analysis runs/preview.analysis.json
```

`measure` 计算客观数值，`check_rules` 产生中文建议，`analyze` 组合两者。
包含整体及每层的 LUFS、峰值、频段功率、左右能量差和单轨能量占比。
频段功率按 [Welch 功率谱密度](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.welch.html) 乘频率分辨率后求和。
占比分母是所有单轨功率之和；混音中的相干交叉项不计入占比分母。

`mixing_rules.json` 中原有阈值保持可编辑；`checks` 中每项支持 `enabled` 和 `severity`（`info` 或 `warning`）。
可分别开关 `masking`、`dominance`、`layer_count`、`event_rate` 和 `stereo_imbalance`。
工具结果的 `success` 表示执行成功，`ok` 表示没有任何建议。提示级别均不阻止提交。
静音或无法测量时使用 JSON `null`；单侧声道完全静音时另记 `silent_channel`，不写 Infinity。

## 运行产物

每次 agent 运行独立写入 `runs/<UTC 时间戳>/`：

- `inputs.json`：实际 prompt、指导、模板、声音目录、素材 SHA256、规则、工具定义和公开模型配置。
- `trace.jsonl`：带时间戳的完整请求、响应（含 usage）、工具调用、工具结果和最终状态。
- `iter_<n>.json`、`iter_<n>.wav`、`iter_<n>.analysis.json`：每次试听的配方、音频与分析。
- `draft.json`、`draft.wav`、`draft.analysis.json`：第一版配方及与终稿相同时长的音频、分析。
- `final.json`、`final.wav`、`final.analysis.json`、`explanation.md`：最终结果与中文解释。

使用非占位素材时，各 WAV 另附同名 `.credits.md`；最终解释也保留实际使用的素材来源与许可。

失败运行仅保存已完成的部分，不会伪造有效配方。密钥与请求头不写入记录，服务地址隐藏账户信息、查询参数和片段。
素材记录校验和，不复制音频；要重新渲染旧结果，仍需要保留对应素材。
一轮开始时固定素材字节，在等待模型期间替换文件不会改变当前运行或其哈希；新文件在下一次运行生效。

## 配方与声音资料

[`templates/window_rain.recipe.json`](templates/window_rain.recipe.json) 是可直接渲染的例子。
参数范围沿用[原始规格](docs/specs/yoin-v0-original.md)，修订以[讨论决策](docs/specs/decisions.md)为准。

- `schema_version` 当前为 1，旧配方省略时按 1 处理。
- `layer_id` 标识配方中的一层；`sound_id` 标识素材。重复使用同一素材时也能有不同层标识。
- 省略层标识时按素材 id 自动生成，重复项加编号；需要稳定局部修改时请显式填写。
- 只有 event 层可以填写 `events_per_minute` 和 `randomness`；前者必填，0 表示不触发，后者默认 0.5。
- 输入音频必须为 48000 Hz，并与声音描述中的 mono/stereo 一致；v0 不自动重采样。
- `library.json` 为声音描述数组，音频路径相对这个文件所在目录解析。
- 声音描述的 `gain_db` 为素材校准增益，默认 0，范围 -60 到 24 dB。
- `tonal`、`musical_key`、`bpm` 为可选资料，本阶段不据此改变音频或做节拍同步。

所有输入校验、命令行错误均以中文说明。渲染时长为 1–300 秒整数，默认 30 秒。
输出路径不能覆盖声音库中的任何素材。参数校验失败时进程退出码为 2。

## 渲染接口

`render(recipe, library, seconds, target_lufs=...)` 不访问模型，也不写文件。
`RenderResult` 返回最终立体声数组、校验后的配方、按 layer_id 索引的单轨、事件时间、
总线增益、归一化前后响度与峰值，以及采样率和渲染器版本。

单轨包含该层的混响贡献，应用与总混音相同的总线增益；各单轨相加在浮点误差内等于最终混音。
CLI 负责读取规则中的目标响度和写出 WAV，后续 agent 可以复用同一个渲染接口。

处理顺序为铺满时长 → 二阶低通 → 音量／距离／素材校准增益 → 声像 → 共用房间混响 → 总线处理。
完整公式在渲染器注释及规格中。房间脉冲响应使用独立随机流，尾音截取为请求时长。
循环接口交叉淡化重叠 0.5 秒，素材实际重复周期因重叠而缩短 0.5 秒。

总线先归一化到 `mixing_rules.json` 的 `target_lufs`，再整体压低以满足 -1 dBFS 峰值上限。
峰值限制生效时，最终响度可能低于目标。静音或低于测量门限时跳过响度提升，无法测量的数值用 `None` 表示。
音量和距离作用于相对层次；单独一层调低后，总线可能重新将它放大。
距离衰减可用 `audio / master_gain` 在归一化前检查。

相同环境、素材、配方、种子和时长产生逐采样相同结果。每层及房间使用独立的随机流，
延长时长或添加其他层不会改变已有事件的随机安排。总线响度增益可能随时长改变。

## 和作曲合作者一起调整

[`templates/TEMPLATE.md`](templates/TEMPLATE.md) 提供统一的交付格式，
[`templates/window_rain.md`](templates/window_rain.md) 是开发示例，尚未经过听感确认。
每个模板由设计说明和具体配方组成，渲染器直接读取具体配方。
[`prompts/system.md`](prompts/system.md) 是可编辑的系统指导，
[`guidance/mixing.md`](guidance/mixing.md) 保存调参说明。运行时会读取指导目录中的 Markdown，
以及模板目录中成对的 `.md`／`.recipe.json`，校验参考配方并注入 prompt。
修改文件会在下一次运行生效；空白交付格式 `TEMPLATE.md` 不作为参考配方载入。

建议先提供三份参考配方及试听说明。素材资料、搭配建议与试听反例都可以一起维护。
当前不实现模板检索、可执行规则语言、时间编排或新效果器。

## 验证与后续工作

测试使用标准库 unittest，没有新增测试依赖：

```bash
python -m unittest tests.test_agent tests.test_model tests.test_codex_model tests.test_connections tests.test_claude_model tests.test_runs tests.test_web -v
```

覆盖声像、归一化前的距离衰减、循环接缝、实际事件次数、独立随机流、确定性、
混响单轨、响度与峰值、静音、占位素材、混音规则、循环预算、错误恢复、中文错误与 SDK HTTP 往返。
HTTP 验收使用本机脚本服务，包含默认 120 秒初稿／终稿的 CLI 测试，不调用付费模型。

保留可试听产物的本地兼容服务演示：

```bash
python -m tests.demo_agent
```

演示经过真实 SDK 和本地 HTTP 服务，但服务返回预设响应，不能当作真实模型能力或听感质量的验收。
真实服务可使用本机 Codex 登录，或配置 API 后运行上述场景命令。

后续任务见 [本地 tickets](.scratch/yoin-v0/issues/)：
阶段 1–4、本机 Codex 入口和本地试听页已实现。验收记录见 [阶段 4 与网页验证](docs/stage-4-web-validation.md)。
