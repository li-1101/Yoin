# 阶段 1 验收记录

日期：2026-10-26。范围：占位声音、声音目录、配方校验、离线渲染器、CLI、模板交付格式。
对照原始规格、已确认决策及 ticket 01；阶段 2–4 不在本次验收范围。

## 自动验证

```bash
.venv/bin/python -m unittest tests.test_schema tests.test_renderer tests.test_placeholders tests.test_cli -v
.venv/bin/python -m pip check
```

结果：34 项测试全部通过；依赖一致性检查通过。测试使用标准库 unittest。
测试覆盖声像、滤波和距离衰减、循环接缝、实际事件次数、随机流、确定性、
混响单轨之和、响度和峰值、静音、素材格式、目录生成以及命令行中文错误。

测试发现并修复随机起点会移动原始素材接缝的问题：先在原始首尾做交叉淡化，再选取随机起点。
回归测试使用有明显首尾落差的斜坡素材，验证渲染后的接缝跳变被消除。

## 实际输出

```bash
.venv/bin/python -m yoin.make_placeholders
.venv/bin/python -m yoin.render templates/window_rain.recipe.json --seconds 60 --out runs/window-rain.wav
```

读取生成文件后的测量：

| 项目 | 结果 |
| --- | --- |
| 时长 | 60 秒 |
| 采样率 | 48000 Hz |
| 声道 | 立体声 |
| 格式 | WAV / FLOAT |
| 整体响度 | -24.0000003 LUFS |
| 峰值 | -10.3165 dBFS |
| 数组 | 全部有限 |

试听文件与素材按约定不纳入 Git。本记录验证技术行为，没有进行人工听感验收。

## Standards

规范审查发现 1 项 P2：无值开关收到显式值时，argparse 的 `ignored explicit argument` 仍显示英文。
已经补充中文映射，并回归验证 `--force=true` 与 `--help=true`。

复核结论：规范审查通过；原英文错误提示已修复，新增回归测试通过，未关闭发现为 0。

## Spec

规格审查发现 1 项 P3：合法的极低事件频率会使平均间隔溢出，随后随机采样抛出异常。
已经对非有限间隔按无事件处理，测试覆盖 `1e-308` 和 `1e-323`。

复核结论：规格审查通过；原发现已关闭，极低事件频率和增强后的独立随机流测试均通过，无剩余规格问题。

总计：Standards 发现 1 项、已关闭 1 项；Spec 发现 1 项、已关闭 1 项；两轴未关闭问题均为 0。

## 验证环境

Python 3.11.9；numpy 2.4.6；scipy 1.17.1；soundfile 0.14.0；pyloudnorm 0.2.0；
pydantic 2.14.1；openai 3.37.0。当前阶段没有模型调用或密钥需求。
