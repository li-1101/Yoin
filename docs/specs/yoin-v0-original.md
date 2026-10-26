# Yoin v0 实现说明：最简单的 agent 循环

> 本文件是交给实现者（人或编码 agent）的任务说明。请严格按本文范围实现，不要添加未列出的功能。

## 0. 一句话目标

用户输入一句中文场景描述（例如"深夜写代码，窗外下着小雨，远处有一点爵士"），程序运行一个 agent 循环：大模型写出一份"配方"，程序把配方离线渲染成音频并做分析，大模型根据分析结果自己修改配方，直到满意后提交。最终输出一个 WAV 文件、一份配方、一段中文解释和完整的过程记录。

v0 是一个 Python 命令行程序，没有界面，不做实时播放。

## 1. 核心概念

- **声音库**：一批音频文件，加上一份描述文件 `library.json`，记录每个声音是什么、适合什么场景。
- **配方（recipe）**：一份 JSON，写明用哪些声音、各自的音量、左右位置、远近、明暗，以及房间混响。它不包含音频本身。
- **渲染器**：读配方和声音库，离线混出一段立体声音频。它是参数含义的"标准实现"，以后的网页播放器要按同样的公式实现。
- **分析器**：对渲染结果做测量，并按混音规则给出警告，比如"钢琴被雨声盖住了"。
- **agent 循环**：大模型反复调用"渲染并分析"工具，根据警告修改配方，最后调用"提交"工具结束。

## 2. 范围

**v0 要做：**
1. 用代码生成一批临时占位声音，并写好 `library.json`
2. 渲染器
3. 分析器和混音规则文件
4. agent 循环，只有两个工具：`render_and_analyze`、`submit_recipe`
5. 在上一次结果基础上继续调整（例如"雨再远一点"）
6. 每次运行的完整过程记录
7. 人工打分命令，用于以后评估"自我修正是否真的让声音更好听"

**v0 不做：** 网页界面、实时播放、用户偏好记忆、AI 生成声音、声音检索工具、手机端、任何 agent 框架（LangChain 等）。

## 3. 技术选择

- Python 3.11+
- 依赖：`numpy`、`scipy`、`soundfile`、`pyloudnorm`、`pydantic`、`openai`
- 大模型通过 **OpenAI 兼容的 Chat Completions 接口 + 工具调用（function calling）** 访问，服务商可配置（DeepSeek、OpenAI、本地兼容服务等）。
- 配置全部来自环境变量，密钥不得写进代码或仓库：
  - `YOIN_API_KEY`
  - `YOIN_BASE_URL`
  - `YOIN_MODEL`
- 采样率统一 48000 Hz，内部计算用 float32 立体声。

## 4. 目录结构

```
yoin/
  pyproject.toml
  README.md
  library.json
  mixing_rules.json
  sounds/                 # 音频文件
  runs/                   # 每次运行的输出（加入 .gitignore）
  yoin/
    __init__.py
    config.py             # 读取环境变量
    schema.py             # 配方与声音描述的数据结构、取值范围、校验
    library.py            # 读取声音库
    renderer.py           # 配方 -> 立体声数组
    analysis.py           # 测量 + 规则检查
    tools.py              # 工具定义（JSON Schema）与执行
    prompts.py            # 系统提示词
    agent.py              # agent 循环
    trace.py              # 过程记录（jsonl）
    make_placeholders.py  # 生成占位声音
    cli.py                # 命令行入口
  tests/
```

## 5. 数据格式

### 5.1 声音描述（library.json 中的一项）

```json
{
  "id": "rain_pink_01",
  "name": "细雨（占位）",
  "description": "均匀的沙沙声，类似中小雨，没有明显特征",
  "kind": "loop",
  "channels": "stereo",
  "file": "sounds/rain_pink_01.wav",
  "tags": ["雨", "白噪音", "均匀"],
  "mood": ["安静"],
  "good_for": ["专注", "助眠"],
  "placeholder": true,
  "source": "程序生成",
  "license": "CC0"
}
```

- `kind`：`loop`（可无缝循环的长片段）或 `event`（偶尔出现的短声音）
- `channels`：`mono` 或 `stereo`
- 以后替换成真实录音时，只需换文件、改描述，代码不变。

### 5.2 配方

```json
{
  "title": "深夜写代码的雨",
  "seed": 0,
  "layers": [
    {"sound_id": "rain_pink_01", "volume": 0.6, "pan": -0.2, "distance": 0.7, "brightness": 0.5},
    {"sound_id": "pad_soft_01",  "volume": 0.4, "pan": 0.1,  "distance": 0.3, "brightness": 0.6},
    {"sound_id": "tick_soft_01", "volume": 0.3, "pan": 0.4,  "distance": 0.2, "brightness": 0.5,
     "events_per_minute": 2, "randomness": 0.5}
  ],
  "room": {"type": "small_room", "amount": 0.3}
}
```

取值范围（`schema.py` 校验，越界或 `sound_id` 不存在时返回清晰的中文错误）：

| 字段 | 范围 | 说明 |
|---|---|---|
| volume | 0–1 | 相对音量 |
| pan | -1–1 | -1 最左，1 最右 |
| distance | 0–1 | 0 贴耳，1 很远 |
| brightness | 0–1 | 0 很闷，1 很亮 |
| events_per_minute | 0–30 | 仅 event 层，必填 |
| randomness | 0–1 | 仅 event 层，间隔的随机程度，默认 0.5 |
| room.type | none / small_room / wooden_cabin / hall | 房间类型 |
| room.amount | 0–1 | 混响总量 |
| seed | 整数 | 随机种子，保证同一配方每次渲染结果相同 |

## 6. 渲染器（参数含义的标准实现）

以下公式必须照此实现，并写进代码注释，以后网页播放器会按相同公式实现。

**每一层的处理顺序：** 取音频 → 铺满时长 → 低通滤波 → 增益 → 左右声像 → 分出一路送混响。

1. **铺满时长**
   - `loop`：从随机位置（由 seed 决定）开始，首尾相接铺满，接口处做 0.5 秒等功率交叉淡化。
   - `event`：平均间隔 `m = 60 / events_per_minute` 秒；第一次出现在 `[0, m]` 内随机；之后每次间隔在 `[m(1 - 0.9r), m(1 + 0.9r)]` 内均匀随机，`r` 为 randomness。

2. **低通滤波（远近和明暗共同决定）**
   - 远近对应的截止频率：`fc_d = 18000 * (2000/18000) ** distance`
   - 明暗对应的截止频率：`fc_b = 2000 * (16000/2000) ** brightness`
   - 实际截止频率：`fc = min(fc_d, fc_b)`，用 2 阶巴特沃斯低通滤波器。

3. **增益**
   - 音量：`g_v = volume ** 2`
   - 距离衰减：`-18 * distance` dB
   - 两者相乘。

4. **左右声像**
   - `θ = (pan + 1) * π / 4`
   - 单声道源：`L = cos θ`，`R = sin θ`（等功率）
   - 立体声源：左声道乘 `min(1, √2·cos θ)`，右声道乘 `min(1, √2·sin θ)`

5. **混响送量**：`send = 0.05 + 0.55 * distance`。每层把 `处理后的信号 × send` 送到共用的混响总线。

**房间混响：**
- 不同类型的混响时长：none 为 0，small_room 0.4 秒，wooden_cabin 0.8 秒，hall 2.0 秒。
- 脉冲响应用代码合成：长度等于混响时长，左右声道各一段独立白噪声，乘以 `exp(-6.91 * t / 混响时长)`，再归一化到单位能量。
- `湿声 = 混响总线与脉冲响应做卷积`（`scipy.signal.fftconvolve`）。
- `输出 = 所有层干声之和 + room.amount × 湿声`。

**总线处理：**
- 把整体响度归一化到 `mixing_rules.json` 中的 `target_lufs`（默认 -24 LUFS），用 `pyloudnorm` 测量。
- 如果峰值超过 -1 dBFS，再整体压低到 -1 dBFS。
- 渲染器同时返回每一层的单独音轨（应用与总线相同的归一化增益），供分析器使用。

## 7. 分析器与混音规则

### 7.1 mixing_rules.json（以后由 etsu 修改）

```json
{
  "target_lufs": -24,
  "max_layers": 5,
  "masking_db": 6,
  "dominance_share_pct": 80,
  "max_event_rate_focus": 6,
  "stereo_imbalance_db": 6,
  "bands_hz": {"low": [20, 250], "mid": [250, 4000], "high": [4000, 16000]}
}
```

### 7.2 测量

对整体和每一层分别计算：
- 响度（LUFS）和峰值（dBFS）
- 每一层占总能量的百分比
- 每一层在低、中、高三个频段的能量（dB），用 `scipy.signal.welch` 计算功率谱后按频段求和
- 左右声道的能量差

### 7.3 规则检查（生成中文警告）

1. **被盖住**：某一层能量最高的频段里，如果另一层比它高出 `masking_db` 以上，警告"『A』在中频被『B』盖住（低 9.2 dB）"。
2. **过于突出**：有多层时，某一层占总能量超过 `dominance_share_pct`，警告。
3. **层数过多**：超过 `max_layers`，警告。
4. **偶发声音太频繁**：任一 event 层的 `events_per_minute` 超过 `max_event_rate_focus`，警告（专注场景下会分散注意力）。
5. **左右不平衡**：左右能量差超过 `stereo_imbalance_db`，警告。

### 7.4 返回给大模型的结果

```json
{
  "ok": false,
  "loudness_lufs": -24.0,
  "peak_dbfs": -6.3,
  "layers": [
    {"sound_id": "rain_pink_01", "share_pct": 71.5, "band_db": {"low": -38.1, "mid": -29.4, "high": -31.0}}
  ],
  "warnings": ["『pad_soft_01』在中频被『rain_pink_01』盖住（低 9.2 dB）"],
  "preview_file": "runs/<run_id>/iter_1.wav"
}
```

`ok` 为没有任何警告时的 true。

## 8. 占位声音（make_placeholders.py）

不依赖任何外部素材，用代码生成以下声音并写入 `library.json`，全部标记 `"placeholder": true`：

| id | kind | 生成方式 | 模拟什么 |
|---|---|---|---|
| noise_white_01 | loop | 白噪声，立体声 | 嘶嘶声 |
| rain_pink_01 | loop | 粉噪声，立体声 | 细雨 |
| rain_brown_01 | loop | 褐噪声，立体声 | 远处的大雨、瀑布 |
| roomtone_01 | loop | 低通到 300 Hz 的褐噪声，很轻 | 房间底噪 |
| pad_soft_01 | loop | 几个正弦波组成的柔和和弦，加缓慢的音量起伏 | 音乐铺底 |
| tick_soft_01 | event | 几十毫秒的滤波噪声短脉冲，单声道 | 翻书、键盘 |
| chime_01 | event | 衰减的正弦音，单声道 | 远处的铃声 |

循环素材长度 30–60 秒，首尾做好无缝处理。

## 9. agent 循环

### 9.1 工具（只有两个）

**`render_and_analyze`**
- 参数：`recipe`（对象），`seconds`（整数，默认 30）
- 先校验配方，失败则返回中文错误说明；成功则渲染、保存试听文件、返回第 7.4 节的分析结果。

**`submit_recipe`**
- 参数：`recipe`（对象），`explanation`（字符串，中文）
- 校验配方；成功则结束循环，渲染最终音频（默认 120 秒）。

### 9.2 循环逻辑（不使用任何框架）

```
messages = [system_prompt, user_request]
for step in range(MAX_STEPS):            # MAX_STEPS = 8
    response = llm(messages, tools)
    把 response 加入 messages，并写入过程记录
    if response 没有工具调用:
        提醒它必须调用 submit_recipe 来结束，继续下一轮
        continue
    for 每个工具调用:
        result = 执行工具
        把 result 作为工具结果加入 messages，并写入过程记录
        if 工具是 submit_recipe 且校验通过:
            渲染最终音频，结束
如果达到 MAX_STEPS 仍未提交：用最后一份校验通过的配方作为结果，并在记录里标注"未主动提交"
```

### 9.3 系统提示词（prompts.py）

系统提示词需包含：
1. 角色：你是 Yoin，为用户调配专注时听的背景声音。
2. **完整的声音库目录**：把 `library.json` 中每个声音的 id、名称、描述、kind、channels、tags 直接写进提示词（v0 声音很少，不需要检索工具）。
3. 配方格式和每个参数的含义、取值范围（第 5.2 节）。
4. 工作流程：
   - 理解用户想要的场景和感受
   - 写出第一版配方，调用 `render_and_analyze`
   - 阅读警告并修改，最多修改 3 次
   - 调用 `submit_recipe`，附上中文解释：选了哪些声音、为什么，以及根据分析改了什么
5. 约束：
   - 只能使用目录里存在的 sound_id
   - 专注场景优先 2 到 4 层，偶发声音要稀疏
   - 声音库里没有用户想要的声音时，用最接近的替代，并在解释里坦白说明

### 9.4 在上次结果上继续调整

`--from <run_id>` 时，把上一次的最终配方放进用户消息："当前配方是……，用户希望：雨再远一点"。其余流程相同。

## 10. 过程记录（trace.py）

每次运行生成目录 `runs/<run_id>/`（run_id 用时间戳），包含：
- `trace.jsonl`：每一步一行，类型包括 `llm_request`、`llm_response`、`tool_call`、`tool_result`、`final`，带时间戳
- `iter_<n>.json` 和 `iter_<n>.wav`：每一版配方和对应的试听文件
- `draft.wav`：第一版配方的渲染结果（与 final 时长相同，用于以后对比）
- `final.json`、`final.wav`、`explanation.md`

这些记录是以后研究"agent 的自我修正是否让声音更好听"的数据，务必完整保存。

## 11. 命令行

```bash
python -m yoin.make_placeholders
python -m yoin.run "深夜写代码，窗外下着小雨，远处有一点爵士"
python -m yoin.run --from <run_id> "雨再远一点"
python -m yoin.render path/to/recipe.json --seconds 60 --out out.wav   # 不经过大模型，直接渲染（调试用，也方便 etsu 手写配方试听）
python -m yoin.rate <run_id> --which draft|final --score 1-5 --note "..."
```

`rate` 把打分追加到 `runs/ratings.jsonl`。

## 12. 分阶段实现与验收

按顺序完成，每一阶段测试通过后再进入下一阶段。

**阶段 1：占位声音和渲染器**
- `make_placeholders` 生成全部文件和 `library.json`
- `render` 命令能把一份手写配方渲染成 WAV
- 测试：
  - 单声道源 pan=-1 时右声道接近静音；pan=0 时左右能量相等
  - distance 从 0 增大到 1 时，该层整体能量和高频能量都下降
  - 循环接口处没有明显的跳变（相邻采样差值不超过附近正常差值的若干倍）
  - event 层的实际出现次数接近 `events_per_minute × 分钟数`
  - 同一配方、同一 seed 渲染两次，结果完全相同

**阶段 2：分析器**
- 测试：构造一个响亮的粉噪声加一个很轻的柔和和弦，必须触发"被盖住"的警告；把和弦调大后警告消失

**阶段 3：agent 循环**
- 输入一句描述，8 步以内生成有效配方
- 只使用声音库里的 sound_id
- 分析出现警告时，至少修改一次
- `runs/<run_id>/` 下所有文件齐全

**阶段 4：继续调整和打分**
- `--from` 能在上次配方基础上修改
- `rate` 能正确写入打分

## 13. 实现要求

- 代码保持简短易读，每个模块只做一件事
- 不引入第 3 节以外的依赖，除非确有必要并说明理由
- 所有给用户和大模型看的错误、警告都用中文
- 不要实现第 2 节"不做"列表里的任何功能
