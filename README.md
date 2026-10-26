# Yoin（余韵）

**Your Own Inner Nook**

将场景描述变成背景声音的实验。当前完成范围是 **阶段 1：声音库、配方校验和离线渲染器**。
模型调用、自我调整、分析建议、继续调整和评分命令将在后续 tickets 实现。

## 安装和试听

需要 Python 3.11+。在项目目录执行：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m yoin.make_placeholders
python -m yoin.render templates/window_rain.recipe.json --seconds 30 --out runs/window-rain.wav
```

生成七种占位声音不需要密钥或外部素材。占位声音是噪声、正弦和短脉冲，主要用于验证控制和流程。
`pad_soft_01` 是合成和弦，不能当作真实爵士乐。输出为 48000 Hz、双声道、32 位浮点 WAV。

默认从当前目录读取 `library.json` 与 `mixing_rules.json`。在其他目录调用时，可设置：

```bash
export YOIN_PROJECT_DIR=/path/to/yoin
```

生成的 `sounds/*.wav` 和 `runs/` 不进入 Git；生成的声音目录纳入 Git，方便后续编辑。
新 checkout 中已有标准声音目录、但尚无音频时，可以直接运行生成命令。
重新生成会覆盖声音资料及同名素材，必须显式使用：

```bash
python -m yoin.make_placeholders --force
```

可用 `--seconds 60` 生成更长的循环素材，范围为 30–60 秒。

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
[`guidance/mixing.md`](guidance/mixing.md) 保存可编辑的调参说明，阶段 3 再注入模型 prompt。

建议先提供三份参考配方及试听说明。素材资料、搭配建议与试听反例都可以一起维护。
本阶段不实现模板检索、可执行规则语言、时间编排或新效果器。

## 验证与后续工作

测试使用标准库 unittest，没有新增测试依赖：

```bash
python -m unittest tests.test_schema tests.test_renderer tests.test_placeholders tests.test_cli -v
```

覆盖声像、归一化前的距离衰减、循环接缝、实际事件次数、独立随机流、确定性、
混响单轨、响度与峰值、静音、占位素材和命令行错误。

后续任务见 [本地 tickets](.scratch/yoin-v0/issues/)：
阶段 2 为测量与建议，阶段 3 为两个工具的 agent 循环及过程记录，阶段 4 为继续调整和评分。
