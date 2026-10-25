# Calibre Audiobook

[English](README.md) | **简体中文**

一个 [Calibre](https://calibre-ebook.com) 插件：在 Google Colab 的 GPU 上把 EPUB 转成 M4B 有声书，你自己的电脑不用跑语音模型。
这是我为自己的书库（以中文为主，也有英文）做的，现按原样分享出来。

- **在 Calibre 里一键完成：** 自动申请你的 Colab 账号能拿到的最好的 GPU（G4 → L4 → T4），转换完成后把 M4B 添加到书里，并释放 GPU。
- **中文：** 在 G4 上用 [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) 0.6B 克隆一个平静的参考声音；在 L4 或 T4 上用
  [Kokoro-82M-v1.1-zh](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh)。
- **英文：** [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)（声音 `af_heart`）。
- 基于 [audiblez](https://github.com/santinic/audiblez)，修复了中文文本的处理，并新增了批量的声音克隆引擎。

## 运行要求
- macOS 或 Linux 上的 Calibre 6 及以上版本（已在 macOS 上的 Calibre 9.16 测试）。不支持 Windows，因为 Colab CLI 不支持。
- 有 Colab 计算单元（compute units）的 Google 账号。转换按 GPU 使用时长计费；在 G4 上转一部中篇小说约花 0.75 个计算单元。
- [Colab CLI](https://pypi.org/project/google-colab-cli/)：`uv tool install google-colab-cli`（或
  `pip install google-colab-cli`），然后在终端里运行一次 `colab sessions` 并完成登录。

## 安装
1. 从[最新版本](https://github.com/TerminaD/calibre-audiobook/releases/latest)下载 `audiblez_audiobook.zip`。
2. 在 Calibre 里：**首选项 → 插件 → 从文件加载插件**，选择这个 zip，再选择按钮显示的位置（主工具栏和书籍列表的右键菜单）。重启 Calibre。
   也可以在终端运行 `calibre-customize -a audiblez_audiobook.zip`，然后在 **首选项 → 工具栏和菜单** 里添加 **Convert to audiobook**。

## 使用
1. 选中一本或多本书。这些书要有 EPUB 格式，语言要设为中文或英文（**编辑元数据 → 语言**）。
2. 点击工具栏或右键菜单里的 **Convert to audiobook**。
3. 每本书会成为一个 Calibre 任务（见右下角的 **任务**）。完成后，带章节标记和封面的 M4B 会添加到这本书的格式里。取消任务也会释放对应的 GPU。

一部约 29,000 字的中篇小说（例如张爱玲的《倾城之恋》）从头到尾的耗时：

| GPU | 中文引擎 | 速度 | 耗时 |
|---|---|---|---|
| G4 | Qwen3-TTS 声音克隆，批量 136 | 约 250 字/秒 | 约 5 分钟（约 0.75 个计算单元） |
| L4 | Kokoro v1.1-zh | 约 245 字/秒 | 约 5 分钟 |
| T4 | Kokoro v1.1-zh | 约 115 字/秒 | 约 7 分钟 |

英文在 G4 上约为每秒 1,000 个字符。每次运行另有约一分钟的准备时间（申请 GPU、安装依赖、加载模型）。

不用 Calibre 的话，克隆本仓库后运行 `python3 colab_audiblez.py [-l zh|en] [--gpus G4,L4,T4] book.epub`，会在 EPUB 旁边生成 `book.m4b`。

### 局限
- 只支持中文和英文书，按 Calibre 的语言字段判断。每种语言只有一个声音，而且中文用哪个声音取决于你拿到的 GPU。
- Qwen 偶尔会在一段文本结束后停不下来。这样的段落会重新生成；如果同一段连续失败四次，转换会停止，并报错显示这一段的开头。
- 进度百分比可能超过 100%。这是上游 audiblez 把"书名 – 作者"开场白另算导致的。
- 与 Colab 的连接中断会让任务失败（GPU 仍会被释放），重新运行即可。

## 工作原理
1. **插件**（`calibre_plugin/ui.py`）：把书的 EPUB 复制到临时文件夹，以 Calibre 任务的形式运行 `colab_audiblez.convert()`。
2. **运行器**（`colab_audiblez.py`，只用标准库）：
   - 依次尝试 `colab new --gpu G4`、L4、T4。申请本身就是 Colab 唯一的可用性检查方式。
   - 上传 EPUB 和一个 **payload zip**（我们的 audiblez 包和参考声音），把依赖安装到 Colab 的 Python 里，运行 `python -m audiblez.cli`，再下载 M4B。
   - 总会在 `finally` 里执行 `colab stop`。丢失连接的 `colab exec` 会被强制结束，因为它可能卡住而不退出。
3. **audiblez**（`audiblez/`，修改过的副本）：
   - **Kokoro：** 中文按段落朗读，`split_to_fit` 让每个分段都在 Kokoro 510 个音素的上限以内。上游版本会悄悄丢掉一段中约 130 个汉字之后的全部内容。
     v1.1-zh 的声音（`zf_001` … `zm_100`）还会给英文单词注音，并用 hexgrad 的方法放慢长分段的语速。
   - **Qwen**（`audiblez/qwen.py`）：只用 `voices/vivian_calm.wav` 及其文字稿构建一次声音克隆提示，之后每个分段都复用它，所以全书是同一个声音；预设声音和风格提示则会在分段之间漂移。
     - 不超过 150 字的分段跨章节批量生成，批量取 GPU 显存允许的最大值（`max_batch_size`，基于拟合的显存模型）。显存不足时批量减半。
     - 时长上限（每秒 3 字再加 2 秒）用来拦住停不下来的分段。
   - **M4B：** 各章节的 WAV 用 ffmpeg 内置的 AAC 一次编码，并加上章节标记和封面。

## 在此基础上开发
| 路径 | 内容 |
|---|---|
| `calibre_plugin/` | Calibre 界面插件（`__init__.py`、`ui.py`）及其图标（`images/`） |
| `colab_audiblez.py` | Colab 运行器，也可以当命令行工具用 |
| `build_plugin.py` | 构建 `dist/audiblez_audiobook.zip`，里面打包了 `audiblez/` 和 `voices/` 的 payload |
| `audiblez/` | 改过的 audiblez：改了 `core.py` 和 `cli.py`，新增 `qwen.py` |
| `voices/` | 用于声音克隆的参考音频，每个都配有一字不差的文字稿（`.txt`） |
| `icons/` | 工具栏和菜单图标的 SVG 源文件，以及 `render_icons.py` |

- **不经过 Calibre 试改动：** `python3 colab_audiblez.py --gpus T4 book.epub` 会上传你的工作副本，所以对 `audiblez/` 或运行器的修改下次运行就生效。T4 是最便宜的 GPU。
- **安装你自己的构建：** `python3 build_plugin.py && calibre-customize -a dist/audiblez_audiobook.zip`，然后重启 Calibre。
  用 `calibre-debug -g` 启动 Calibre 可以看到插件的输出和报错信息。
- **更换声音或引擎：** `colab_audiblez.py` 里的 `VOICES` 按语言和 GPU 指定声音。`.wav` 路径表示用 Qwen 克隆，其他值则是 Kokoro 的声音名称。
  - 要新增一个克隆声音，把一段干净的 5–20 秒音频和一字不差的文字稿（同名 `.txt`）放进 `voices/`。
  - Kokoro 那边可以用 v1.1-zh 的 100 个声音中的任意一个（`zf_001` … `zm_100`）。
- **更换 Qwen 模型或分段方式：** 见 `audiblez/qwen.py` 开头的常量。改了 `MODEL`、`MAX_CHUNK_CHARS`、`MIN_CHARS_PER_SECOND` 或参考音频后，要重新拟合 `MEMORY_GB`：
  - 在几个批量下测量 `torch.cuda.max_memory_allocated()`，并让每个分段都跑到时长上限。把 `eos_token_id` 设成一个被模型屏蔽的编码 id 就能做到。
  - 用这几个点拟合一条直线。
- **图标：** 修改 `icons/*.svg`，然后运行 `calibre-debug icons/render_icons.py`。图标按 Calibre 的 *San Francisco* 图标主题风格绘制，分浅色和深色两版。
- **发布：** 提高 `calibre_plugin/__init__.py` 里的 `version`，运行 `python3 build_plugin.py`，再运行
  `gh release create vX.Y.Z dist/audiblez_audiobook.zip`。

## 许可证
[CC BY-NC 4.0](LICENSE)：任何非商业用途都可以自由使用、修改和分享，但需注明出处；不允许商业用途。（因此它属于"源码公开"，而不是 OSI 定义的开源。）
`audiblez/` 目录基于 Claudio Santini 的 [audiblez](https://github.com/santinic/audiblez)，采用 MIT 许可证（见 `audiblez/LICENSE`）。
模型在运行时下载，遵循各自的许可证：Kokoro-82M 和 Qwen3-TTS 均为 Apache 2.0。

## 致谢
[audiblez](https://github.com/santinic/audiblez)（Claudio Santini）、
[Kokoro](https://huggingface.co/hexgrad/Kokoro-82M)（hexgrad）、
[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)（阿里云通义千问团队）、
[Colab CLI](https://pypi.org/project/google-colab-cli/)（Google）和 [Calibre](https://calibre-ebook.com)（Kovid Goyal）。
