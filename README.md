# Calibre Audiobook

**English** | [简体中文](README.zh-CN.md)

A [Calibre](https://calibre-ebook.com) plugin that turns EPUBs into M4B audiobooks on a Google Colab GPU, so your own
machine never runs a speech model. I built it for my own library (mostly Chinese, some English) and am sharing it as is.

- **One click in Calibre:** it takes the best GPU your Colab account can get (G4 → L4 → T4), converts the book, adds
  the M4B to it, and releases the GPU.
- **Chinese:** [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) 0.6B cloning one calm reference voice on a G4;
  [Kokoro-82M-v1.1-zh](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh) on an L4 or T4.
- **English:** [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (voice `af_heart`).
- Based on [audiblez](https://github.com/santinic/audiblez), with fixes for Chinese text and a batched voice-cloning engine.

## Requirements
- Calibre 6 or later on macOS or Linux (tested with Calibre 9.16 on macOS). Windows isn't supported, because the
  Colab CLI isn't.
- A Google account. **A free Colab account works:** the free tier offers a T4 GPU when one is available, and the
  plugin uses it at no cost (Chinese is then read by Kokoro v1.1-zh). Paid Colab compute units add the L4 and G4,
  and with it the Qwen voice clone. A novella costs about 0.75 units on a G4.
- The [Colab CLI](https://pypi.org/project/google-colab-cli/): `uv tool install google-colab-cli` (or
  `pip install google-colab-cli`), then run `colab sessions` once in a terminal and complete the sign-in.

## Install
1. Download `audiblez_audiobook.zip` from the [latest release](https://github.com/TerminaD/calibre-audiobook/releases/latest).
2. In Calibre: **Preferences → Plugins → Load plugin from file**, choose the zip, and pick where the button should
   appear (the main toolbar and the book list's right-click menu). Restart Calibre.
   From a terminal, `calibre-customize -a audiblez_audiobook.zip` does the same; then add **Convert to audiobook**
   under **Preferences → Toolbars & menus**.

## Use
1. Select one or more books that have an EPUB format and whose language is set to Chinese or English
   (**Edit metadata → Languages**).
2. Click **Convert to audiobook** in the toolbar or the right-click menu.
3. Each book becomes a Calibre job (see **Jobs** at the bottom right). When it finishes, the M4B, with chapter marks
   and cover, is added to the book's formats. Cancelling a job also releases its GPU.

A ~29,000-character novella (e.g. 张爱玲's 倾城之恋), end to end:

| GPU | Chinese engine | Speed | Time |
|---|---|---|---|
| G4 | Qwen3-TTS voice clone, batch 136 | ~250 chars/s | ~5 min (~0.75 compute units) |
| L4 | Kokoro v1.1-zh | ~245 chars/s | ~5 min |
| T4 | Kokoro v1.1-zh | ~115 chars/s | ~7 min (free on a free account) |

English runs at about 1,000 chars/s on a G4. Each run also spends about a minute on setup (allocating the GPU,
installing dependencies, loading the model).

Without Calibre, from a clone of this repo: `python3 colab_audiblez.py [-l zh|en] [--gpus G4,L4,T4] book.epub` writes
`book.m4b` next to the EPUB.

### Limitations
- Only Chinese and English books, decided by Calibre's language field. One voice per language, and the Chinese
  voice depends on the GPU you get.
- Qwen occasionally doesn't stop at the end of a chunk. Such chunks are regenerated; if one fails four times, the
  conversion stops with an error that quotes the start of the chunk.
- The progress percentage can pass 100%. That's upstream audiblez counting the "title – author" intro separately.
- A dropped connection to Colab fails the job (the GPU is still released); just run it again.
- On a free account the T4 isn't guaranteed: when none is available, the job fails with "Could not get a G4, L4, T4
  GPU". Try again later. Rejected requests for the L4 and G4 cost nothing.

## How it works
1. **Plugin** (`calibre_plugin/ui.py`): copies the book's EPUB to a temp folder and runs `colab_audiblez.convert()` as
   a Calibre job.
2. **Runner** (`colab_audiblez.py`, stdlib only):
   - Tries `colab new --gpu G4`, then L4, then T4. Allocating is the only availability check Colab offers.
   - Uploads the EPUB and a **payload zip** (our audiblez package and the reference voice), installs dependencies
     into Colab's Python, runs `python -m audiblez.cli`, and downloads the M4B.
   - Always runs `colab stop` in `finally`. A `colab exec` that loses its connection is killed, since it can hang
     instead of exiting.
3. **audiblez** (`audiblez/`, a modified copy):
   - **Kokoro:** Chinese is read a paragraph at a time, and `split_to_fit` keeps each chunk under Kokoro's
     510-phoneme limit. Upstream silently dropped everything past ~130 Chinese characters of a paragraph. v1.1-zh
     voices (`zf_001` … `zm_100`) also get English words phonemized and hexgrad's slowdown for long chunks.
   - **Qwen** (`audiblez/qwen.py`): a voice-clone prompt is built once from `voices/vivian_calm.wav` and its
     transcript, then reused for every chunk. That keeps one voice throughout; preset voices and style prompts
     drifted from chunk to chunk.
     - Chunks of ≤150 characters are batched across chapters, at the largest batch the GPU's memory allows
       (`max_batch_size`, from a fitted memory model). Out-of-memory halves the batch.
     - A length cap (3 chars/s + 2 s) catches chunks that never stop.
   - **M4B:** the chapter WAVs are encoded once with ffmpeg's built-in AAC, with chapter marks and the cover.

## Building on it
| Path | What it is |
|---|---|
| `calibre_plugin/` | The Calibre interface plugin (`__init__.py`, `ui.py`) and its icons (`images/`) |
| `colab_audiblez.py` | The Colab runner, also usable as a CLI |
| `build_plugin.py` | Builds `dist/audiblez_audiobook.zip`, with a payload of `audiblez/` and `voices/` inside |
| `audiblez/` | audiblez with our changes: `core.py` and `cli.py` changed, `qwen.py` added |
| `voices/` | Reference clips for voice cloning, each with its exact transcript (`.txt`) |
| `icons/` | SVG sources for the toolbar and menu icons, and `render_icons.py` |

- **Try changes without Calibre:** `python3 colab_audiblez.py --gpus T4 book.epub` uploads your working copy, so
  edits to `audiblez/` or the runner take effect on the next run. T4 is the cheapest GPU.
- **Install your build:** `python3 build_plugin.py && calibre-customize -a dist/audiblez_audiobook.zip`, then restart
  Calibre. Start it with `calibre-debug -g` to see the plugin's output and tracebacks.
- **Change voices or engines:** `VOICES` in `colab_audiblez.py` maps language and GPU to a voice. A `.wav` path means
  a Qwen clone; anything else is a Kokoro voice name.
  - For a new cloned voice, add a clean 5–20 s clip and its exact transcript (same name, `.txt`) to `voices/`.
  - For the Kokoro side, any of v1.1-zh's 100 voices works (`zf_001` … `zm_100`).
- **Change the Qwen model or chunking:** see the constants at the top of `audiblez/qwen.py`. After changing `MODEL`,
  `MAX_CHUNK_CHARS`, `MIN_CHARS_PER_SECOND` or the reference clip, refit `MEMORY_GB`:
  - Measure `torch.cuda.max_memory_allocated()` at a few batch sizes, with every chunk forced to the length cap.
    Passing `eos_token_id` set to a codec id the model suppresses does that.
  - Fit a line through the points.
- **Icons:** edit `icons/*.svg`, then run `calibre-debug icons/render_icons.py`. They're drawn to match Calibre's
  *San Francisco* icon theme, in light and dark variants.
- **Release:** bump `version` in `calibre_plugin/__init__.py`, run `python3 build_plugin.py`, then
  `gh release create vX.Y.Z dist/audiblez_audiobook.zip`.

## License
[CC BY-NC 4.0](LICENSE): use, change and share it freely for any noncommercial purpose, with credit; commercial use
isn't allowed. (That makes it source-available rather than OSI open source.) The `audiblez/` directory is based on
[audiblez](https://github.com/santinic/audiblez) by Claudio Santini, MIT License (`audiblez/LICENSE`). The models are
downloaded at run time under their own licenses: Kokoro-82M and Qwen3-TTS are Apache 2.0.

## Credits
[audiblez](https://github.com/santinic/audiblez) (Claudio Santini),
[Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) (hexgrad),
[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) (Qwen team, Alibaba Cloud),
the [Colab CLI](https://pypi.org/project/google-colab-cli/) (Google), and [Calibre](https://calibre-ebook.com)
(Kovid Goyal).
