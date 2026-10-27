# 下载声音来源

获取日期：2026-10-27。原始文件保存在本地缓存，处理后的短 WAV 随项目保存。
完整原始下载地址、时间截取区间、重采样及滤波参数、原文件和输出 SHA256 见
[`sources.json`](../sounds/recorded/sources.json)。

| 素材 | 作者和原始页面 | 许可 |
| --- | --- | --- |
| 单颗水滴（默认） | [Single Water Drop — paespedro](https://freesound.org/people/paespedro/sounds/174718/) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| 细碎水声（旧版） | [Water Drops — CeoxBlackj](https://opengameart.org/content/water-drops) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| 鸟叫 | [Bird chirping sounds — syncopika](https://lpc.opengameart.org/content/bird-chirping-sounds) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| 翻书页 | [Page Turning Sfx Sound Effect — Nicole Marie T](https://opengameart.org/content/page-turning-sfx-sound-effect) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

翻书素材署名：**Sound Effect By Nicole Marie T**。
修改包括截取、转单声道、重采样、滤波、首尾淡化和电平校准。没有将修改后的素材标记为 CC0。
使用这些素材的输出附带来源说明；分享音频时请一并保留来源和许可信息。

用户反馈之前的合成雨声高频刺耳。新阅读模板不使用持续噪声铺底，关闭房间混响，
降低鸟叫和翻页的明暗、突出程度，并将规则中的目标响度从 -24 调整为 -30 LUFS。
这是本次试听调整，渲染公式保持不变。

用户进一步反馈旧水声听起来像水流。默认水层改为 `water_drop_single_01`，选用 paespedro 的单颗水滴拟音。
原作者说明为口部与手部制作；使用公开 HQ MP3 预览，截取 0.01–0.34 秒并按清单处理。
每次事件约 0.33 秒，滴声之间留白；旧文件和旧 sound_id 保留，历史音频不会被覆盖。
本机单独试听：`runs/water-drop-single-preview.wav`，12 秒内有四次滴声。

## 古典音乐

以下两个具体音频文件均由来源页面标记为 [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)，
允许免费商用、复制与改编，无需额外申请授权；许可核对包含录音／音源本身。

| 曲目 | 音源与许可页面 | 长度 | sound_id |
| --- | --- | --- | --- |
| 巴赫《C 大调前奏曲 BWV 846》 | [Kimiko Ishizaka，Open Well-Tempered Clavier](https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_01_Prelude_No._1_in_C_major,_BWV_846.ogg)，CC0；[演奏者专辑说明](https://kimikoishizaka.bandcamp.com/album/bach-well-tempered-clavier-book-1)也确认 CC0 | 2:43 | `bach_prelude_c_major_01` |
| 萨蒂《第一号吉姆诺佩蒂》 | [Teknopazzo 发布的音源](https://commons.wikimedia.org/wiki/File:Gymnopedie_No._1..ogg)，来源为作者自己的作品，文件明确标记 CC0 | 3:25 | `satie_gymnopedie_1_01` |

获取日期：2026-10-27。整曲保存在 `sounds/music/`，保留立体声，重采样为 48000 Hz，
加 20 ms 首尾淡化并校准电平，以 24 位 PCM FLAC 保存；渲染内部仍为 float32。
巴赫原文件为 96 kHz，萨蒂原文件为 22.05 kHz，重采样不增加原始录音的频率信息。
处理参数、下载地址和前后 SHA256 见 [`sounds/music/sources.json`](../sounds/music/sources.json)。
原始下载文件保存在本地导入缓存。

音乐已登记进 `library.json`，下一次生成会自动载入。例如输入：
“用巴赫 C 大调前奏曲做很轻的背景，偶尔翻页，不要雨声”。默认不同时叠加两首音乐。
运行时仍按现有 loop 逻辑取段；库中整曲保持完整。

## 环境声

用户确认保留现有水滴后，新增四种环境录音。下面四份具体音源的来源页面均标记为 CC0，
可免费商用和改编；本轮使用公开 HQ MP3 预览，原始文件需要在来源网站登录下载。

| 素材 | 音源与 CC0 来源 | 库内片段 | sound_id |
| --- | --- | --- | --- |
| 海浪拍岸 | [Slow Waves, Stony Beach — Kinoton](https://freesound.org/people/Kinoton/sounds/635917/) | 45 秒 | `ocean_waves_01` |
| 风吹树叶 | [Wind in trees 1.mp3 — alppdcjr12](https://freesound.org/people/alppdcjr12/sounds/662575/) | 40 秒 | `wind_leaves_01` |
| 篝火噼啪 | [Ambiance_Campfire_Loop_Stereo.wav — Nox_Sound](https://freesound.org/people/Nox_Sound/sounds/558967/) | 约 12.73 秒 | `campfire_01` |
| 夏夜虫鸣 | [Crickets At Night - Clean sound — Defelozedd94](https://freesound.org/people/Defelozedd94/sounds/522298/) | 45 秒 | `night_crickets_01` |

获取日期：2026-10-27。处理后片段保存在 `sounds/ambience/`，登记为 loop，并保留立体声。
重采样为 48000 Hz，加 30 Hz 二阶高通、20 ms 首尾淡化，峰值校准为 0.25，以 24 位 PCM FLAC 保存。
FLAC 是转存格式，不代表恢复了 MP3 来源丢失的信息。完整取段、来源和前后哈希见
[`sounds/ambience/sources.json`](../sounds/ambience/sources.json)。

本机 `runs/ambience-preview/` 提供四段独立的 30 秒试听及 `index.html` 试听页。
试听用现有渲染器生成，目标 -30 LUFS，关闭混响，导出为兼容常见播放器的 16 位 PCM WAV。
素材库和标准 agent 的内部渲染仍为 float32。当前水滴与已有混音没有重新替换或覆盖。

下一次生成可直接说：“黄昏海边，以轻海浪为主，偶尔翻页，不要音乐”。
