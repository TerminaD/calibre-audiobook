# -*- coding: utf-8 -*-
"""Qwen3-TTS voice cloning: read every chunk in the voice of one reference clip, many chunks per GPU call.

A preset voice or a style instruction is sampled afresh for each chunk, so the voice drifts between chunks; a
voice-clone prompt built once from a reference clip conditions every chunk on the same audio and keeps it steady.
"""
from pathlib import Path

import soundfile
import torch
from qwen_tts import Qwen3TTSModel

MODEL = 'Qwen/Qwen3-TTS-12Hz-0.6B-Base'
LANGUAGE = 'Chinese'  # the only language we have a reference clip for
MAX_CHUNK_CHARS = 150  # about the longest chunk tested; longer inputs are split by core.split_to_fit
FRAMES_PER_SECOND = 12.5  # codec frames, i.e. generated tokens, per second of audio
# Length cap: a chunk that never emits its stop token would run to the model's 8192-frame limit (~11 min) and hold up
# its whole batch, which happens to ~1-2% of chunks. Our voice reads 4-5 chars/s, so 3 chars/s (+2 s) leaves margin.
MIN_CHARS_PER_SECOND = 3
MAX_RETRIES = 3  # a chunk that still hits the cap after this many redos stops the conversion with an error
# Peak GPU memory in GB ~ fixed + per_item * batch size, for MAX_CHUNK_CHARS chunks all running to the length cap and
# a ~16 s reference. Fitted to torch.cuda.max_memory_allocated() over batches with the stop token suppressed (so every
# chunk runs to the cap, the worst case): bf16 on a G4 (32-136; 160 ran out of memory) and an L4 (8-24; 32 ran out),
# fp32 on a T4 (1-8). Refit after changing MODEL, MAX_CHUNK_CHARS, MIN_CHARS_PER_SECOND or the reference clip.
MEMORY_GB = {torch.bfloat16: (5.97, 0.613), torch.float32: (4.43, 1.126)}


def dtype():
    # bf16 needs Ampere or newer (L4, G4). T4 gets fp32: in fp16 the sampling probabilities overflow
    # ("CUDA error: device-side assert triggered").
    return torch.bfloat16 if torch.cuda.get_device_capability(0) >= (8, 0) else torch.float32


def load(ref_wav):
    """Load the Base model and build the voice-clone prompt from ref_wav, whose transcript is the .txt beside it."""
    model = Qwen3TTSModel.from_pretrained(MODEL, device_map='cuda:0', dtype=dtype(), attn_implementation='sdpa')
    audio, sr = soundfile.read(ref_wav)
    ref_text = Path(ref_wav).with_suffix('.txt').read_text(encoding='utf-8').strip()
    # ICL mode: chunks are conditioned on the reference's speech codes and transcript, not just a speaker embedding
    return model, model.create_voice_clone_prompt(ref_audio=(audio, sr), ref_text=ref_text)


def max_batch_size():
    """Largest batch the GPU's memory allows, by the memory model above."""
    total_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    fixed, per_item = MEMORY_GB[dtype()]
    size = int((0.9 * total_gb - fixed) / per_item)
    size = size // 8 * 8 if size >= 8 else max(size, 1)
    print(f'Using GPU {torch.cuda.get_device_name(0)} ({total_gb:.0f} GB), batch size {size}')
    return size


def cap_seconds(text):
    return len(text) / MIN_CHARS_PER_SECOND + 2


def generate(model, prompt, texts, **kwargs):
    """Generate texts in one batch under the length cap; return the waveforms and which ones hit the cap."""
    cap = int(max(map(cap_seconds, texts)) * FRAMES_PER_SECOND)
    wavs, sr = model.generate_voice_clone(text=texts, language=LANGUAGE, voice_clone_prompt=prompt,
                                          max_new_tokens=cap, **kwargs)
    return wavs, [len(wav) / sr >= cap_seconds(text) - 0.5 for text, wav in zip(texts, wavs)]


def synthesize(model, prompt, chunks, batch_size):
    """Yield one waveform per chunk, in order, generating batch_size chunks per call. A chunk that hit the length cap
    is redone at the front of the next batch (no extra call), up to MAX_RETRIES times; the batch is halved on
    out-of-memory."""
    queue, done, next_out, retries = list(range(len(chunks))), {}, 0, {}
    while queue:
        batch = queue[:batch_size]
        try:
            wavs, overlong = generate(model, prompt, [chunks[k] for k in batch])
        except torch.OutOfMemoryError:
            if batch_size == 1:
                raise
            torch.cuda.empty_cache()
            batch_size //= 2
            print(f'Out of GPU memory, retrying with batch size {batch_size}')
            continue
        queue = queue[len(batch):]
        redo = [k for k, too_long in zip(batch, overlong) if too_long]
        for k in redo:
            retries[k] = retries.get(k, 0) + 1
            if retries[k] > MAX_RETRIES:
                raise RuntimeError(f'A chunk kept running past its length cap after {MAX_RETRIES} retries, so the '
                                   f'conversion was stopped. The chunk starts: {chunks[k][:40]}')
        if redo:
            print(f'Redoing {len(redo)} chunk(s) that ran too long: ' + ', '.join(chunks[k][:12] for k in redo))
        queue = redo + queue
        done.update((k, wav) for k, wav in zip(batch, wavs) if k not in redo)
        while next_out in done:
            yield done.pop(next_out)
            next_out += 1
