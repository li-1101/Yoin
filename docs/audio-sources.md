# 下载声音来源

获取日期：2026-10-27。原始文件保存在本地缓存，处理后的短 WAV 随项目保存。
完整原始下载地址、时间截取区间、重采样及滤波参数、原文件和输出 SHA256 见
[`sources.json`](../sounds/recorded/sources.json)。

| 素材 | 作者和原始页面 | 许可 |
| --- | --- | --- |
| 水滴 | [Water Drops — CeoxBlackj](https://opengameart.org/content/water-drops) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| 鸟叫 | [Bird chirping sounds — syncopika](https://lpc.opengameart.org/content/bird-chirping-sounds) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| 翻书页 | [Page Turning Sfx Sound Effect — Nicole Marie T](https://opengameart.org/content/page-turning-sfx-sound-effect) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

翻书素材署名：**Sound Effect By Nicole Marie T**。
修改包括截取、转单声道、重采样、滤波、首尾淡化和电平校准。没有将修改后的素材标记为 CC0。
使用这些素材的输出附带来源说明；分享音频时请一并保留来源和许可信息。

用户反馈之前的合成雨声高频刺耳。新阅读模板不使用持续噪声铺底，关闭房间混响，
降低鸟叫和翻页的明暗、突出程度，并将规则中的目标响度从 -24 调整为 -30 LUFS。
这是本次试听调整，渲染公式保持不变。

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
