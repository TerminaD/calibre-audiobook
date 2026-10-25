#!/usr/bin/env python3
"""Convert an EPUB to an .m4b audiobook with our audiblez on a Colab GPU, then release the GPU.

Usage: python3 colab_audiblez.py [-l zh|en] [-s SPEED] [--gpus G4,L4,T4] book.epub

Each run takes the first GPU in the ladder the account can allocate. Chinese is read by Qwen3-TTS cloning
voices/vivian_calm.wav on a G4 (batched to the GPU's memory), and by Kokoro-82M-v1.1-zh (zf_001) on an L4 or T4;
English by Kokoro (af_heart). Our audiblez package and
the reference voices are uploaded as a zip each run (make_payload), so the VM always runs the local code. Requires
the Colab CLI (`uv tool install google-colab-cli`), signed in once by running `colab sessions` in a terminal.
The .m4b is written next to the EPUB. The Calibre plugin in calibre_plugin/ imports this module.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

GPUS = ('G4', 'L4', 'T4')  # most to least performant; G4 is the cap
# Voice per language and GPU: a .wav is cloned with Qwen3-TTS, anything else is a Kokoro voice. Qwen is ~10x slower on
# an L4 and ~30x on a T4 than on a G4 (~1 h for a novella on a T4), so those read Chinese with Kokoro-82M-v1.1-zh.
VOICES = {
    'zh': {'G4': '/content/audiblez_src/voices/vivian_calm.wav', 'L4': 'zf_001', 'T4': 'zf_001'},
    'en': {'G4': 'af_heart', 'L4': 'af_heart', 'T4': 'af_heart'},
}
# GUI apps on macOS don't get the login shell's PATH; uv and pip put `colab` in one of these.
EXTRA_PATH = [os.path.expanduser('~/.local/bin'), '/opt/homebrew/bin', '/usr/local/bin']
PROGRESS = re.compile(r'^Progress: (\d+)%')

INSTALL_HELP = '''The Colab CLI ("colab") is not installed.

Install it from a terminal:
    uv tool install google-colab-cli
(or: pip install google-colab-cli)

Then sign in once by running:
    colab sessions'''

AUTH_HELP = '''The Colab CLI is not signed in to your Google account.

Open a terminal and run:
    colab sessions
Open the link it prints, approve access, and paste the authorization code back into the terminal. Then try again.'''

# Dependencies of our audiblez (Kokoro for English, Qwen3-TTS for Chinese) minus what Colab preinstalls (torch,
# spacy, librosa, ...). Installed with --no-deps into Colab's Python 3.13: kokoro and misaki declare <3.13 but work,
# and a normal install would download torch again.
SPACY_MODELS = 'https://github.com/explosion/spacy-models/releases/download'
NO_DEPS_PACKAGES = [
    'kokoro==0.9.4', 'misaki==0.9.4', 'qwen-tts==0.1.1', 'loguru==0.7.3', 'addict', 'cn2an==0.5.24', 'proces==0.1.7',
    'jieba', 'ordered-set==4.1.0', 'pypinyin==0.55.0', 'pypinyin-dict', 'espeakng-loader==0.2.4', 'num2words==0.5.14',
    'docopt==0.6.2', 'phonemizer-fork==3.3.2', 'dlinfo==2.0.0', 'segments==2.4.0', 'csvw==4.1.1', 'rfc3986==1.5.0',
    'isodate==0.7.2', 'language-tags==1.3.1', 'rdflib==7.6.0', 'ebooklib==0.18', 'pick==2.6.0',
    f'{SPACY_MODELS}/xx_ent_wiki_sm-3.8.0/xx_ent_wiki_sm-3.8.0-py3-none-any.whl',
    f'{SPACY_MODELS}/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl',
]
DEPS_PACKAGES = ['transformers==4.57.3', 'accelerate==1.12.0', 'onnxruntime', 'sox']  # qwen-tts pins transformers

# Runs in the Colab kernel; NO_DEPS and DEPS are prepended.
REMOTE_SETUP = r'''
import subprocess, sys, zipfile
ok = True
for cmd in ["uv pip install --system -q --no-deps " + " ".join(NO_DEPS), "uv pip install --system -q " + " ".join(DEPS)]:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(r.stdout[-2000:], r.stderr[-2000:])
    ok = ok and r.returncode == 0
zipfile.ZipFile("/content/audiblez_payload.zip").extractall("/content/audiblez_src")
print("Remote Python", sys.version.split()[0])
print("SETUP_OK" if ok else "setup failed")
'''

# Runs in the Colab kernel; VOICE and SPEED are prepended. audiblez runs as a separate process, so its imports stay
# out of the kernel, and its output is relayed line by line.
REMOTE_CONVERT = r'''
import os, subprocess, sys
import espeakng_loader
# Kokoro's audiblez looks for a system espeak-ng (apt); use the copy bundled with espeakng-loader instead.
env = dict(os.environ, PYTHONPATH="/content/audiblez_src", ESPEAK_LIBRARY=espeakng_loader.get_library_path())
p = subprocess.Popen(["python", "-u", "-m", "audiblez.cli", "/content/book.epub", "-v", VOICE, "-s", SPEED, "-o", "/content/out"],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
for line in p.stdout:
    sys.stdout.write(line)
    sys.stdout.flush()
m4b = "/content/out/book.m4b"
print("M4B=" + m4b if p.wait() == 0 and os.path.exists(m4b) else f"FAILED: audiblez exited {p.returncode}")
'''


class ColabError(Exception):
    """A failure whose message is meant for the user."""


def make_payload(root, out_zip):
    """Zip our audiblez package and the reference voices; the VM unzips them onto PYTHONPATH."""
    root = Path(root)
    with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted((root / 'audiblez' / 'audiblez').glob('*.py')):
            z.write(f, f'audiblez/{f.name}')
        for f in sorted((root / 'voices').iterdir()):
            z.write(f, f'voices/{f.name}')
    return str(out_zip)


def _env():
    env = dict(os.environ)
    env['PATH'] = os.pathsep.join(EXTRA_PATH + [env.get('PATH', '/usr/bin:/bin')])
    return env


def find_colab():
    """Return the colab executable; raise ColabError if it is missing or not signed in."""
    colab = shutil.which('colab', path=_env()['PATH'])
    if not colab:
        raise ColabError(INSTALL_HELP)
    try:
        # stdin=DEVNULL: when signed out, colab prompts for an auth code and would wait forever.
        r = subprocess.run([colab, 'sessions'], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, env=_env(), timeout=120)
    except subprocess.TimeoutExpired:
        raise ColabError('"colab sessions" timed out. Check your internet connection and try again.')
    if r.returncode:
        out = (r.stdout + r.stderr).strip()
        if 'authoriz' in out.lower() or 'credentials' in out.lower():
            raise ColabError(AUTH_HELP)
        raise ColabError(f'"colab sessions" failed:\n{out[-1500:]}')
    return colab


def convert(epub, lang='zh', speed=1.0, payload=None, gpus=GPUS, session='audiblez', log=print,
            progress=lambda frac, msg: None, abort=None):
    """Convert epub on a Colab GPU and return the path of the .m4b written next to it.

    payload is the zip from make_payload (the plugin bundles one); if None, it is built from this repository.
    log(line) receives all output; progress(frac, msg) receives status updates. Setting the abort Event cancels
    the conversion. The GPU is released however this function exits.
    """
    colab = find_colab()
    abort = abort or threading.Event()
    frac = 0.0

    def stage(msg):
        log(time.strftime('[%H:%M:%S] ') + msg)
        progress(frac, msg)

    def run(*args, code=None):
        """Run a colab subcommand, logging its output; return (returncode, output lines)."""
        nonlocal frac
        p = subprocess.Popen([colab, *args], stdin=subprocess.PIPE if code else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=_env(),
                             text=True, encoding='utf-8', errors='replace')
        if code:
            p.stdin.write(code)
            p.stdin.close()
        finished = threading.Event()

        def kill_on_abort():
            while not finished.wait(1):
                if abort.is_set():
                    p.kill()
                    return
        threading.Thread(target=kill_on_abort, daemon=True).start()
        lines = []
        for line in p.stdout:  # text mode also splits on \r, so each progress update is a line
            line = line.rstrip()
            lines.append(line)
            if 'Connection was lost' in line:  # colab exec can hang after losing the kernel instead of exiting
                p.kill()
            m = PROGRESS.match(line)
            if m:
                frac = min(int(m.group(1)), 100) / 100  # audiblez's estimate can overshoot 100%
                progress(frac, line)
            elif line:
                log(line)
        p.wait()
        finished.set()
        if abort.is_set():
            raise ColabError('Cancelled.')
        return p.returncode, lines

    def tail(lines):
        return '\n'.join(lines[-15:])

    tmp = tempfile.mkdtemp(prefix='audiblez_payload_')
    payload = payload or make_payload(Path(__file__).parent, os.path.join(tmp, 'audiblez_payload.zip'))
    attempted = allocated = False
    try:
        for gpu in gpus:
            stage(f'Allocating a {gpu} GPU...')
            attempted = True  # a cancelled `colab new` may still have created the VM
            rc, out = run('new', '-s', session, '--gpu', gpu)
            if rc == 0 and any('READY' in line for line in out):
                allocated = True
                break
            log(f'{gpu} is not available on this account right now.')
        else:
            raise ColabError(f'Could not get a {", ".join(gpus)} GPU from Colab. You may be out of compute units '
                             'or have hit a usage limit.\n\n' + tail(out))

        stage('Uploading the EPUB and audiblez...')
        for local, remote in [(epub, '/content/book.epub'), (payload, '/content/audiblez_payload.zip')]:
            rc, out = run('upload', '-s', session, local, remote)
            if rc:
                raise ColabError(f'Uploading {os.path.basename(local)} failed:\n' + tail(out))

        stage('Installing dependencies...')
        rc, out = run('exec', '-s', session, '--timeout', '600',
                      code=f'NO_DEPS = {NO_DEPS_PACKAGES!r}\nDEPS = {DEPS_PACKAGES!r}\n' + REMOTE_SETUP)
        if 'SETUP_OK' not in out:
            raise ColabError('Installing dependencies on the VM failed:\n' + tail(out))

        voice = VOICES[lang][gpu]
        stage(f'Converting with voice {os.path.basename(voice)} on the {gpu}...')
        code = f'VOICE = {voice!r}\nSPEED = {str(speed)!r}\n' + REMOTE_CONVERT
        rc, out = run('exec', '-s', session, '--timeout', '14400', code=code)
        remote = next((line[4:] for line in out if line.startswith('M4B=')), None)
        if not remote:
            # Lead with the exception line (e.g. a chunk that kept running away); the log tail follows
            error = next((line for line in reversed(out) if re.match(r'\w+(Error|Exception): ', line)), '')
            raise ColabError(f'audiblez failed. {error}\n\n' + tail(out))

        local = os.path.splitext(epub)[0] + '.m4b'
        stage('Downloading the audiobook...')
        rc, out = run('download', '-s', session, remote, local)
        if rc or not os.path.exists(local):
            raise ColabError('Downloading the audiobook failed:\n' + tail(out))
        return local
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if attempted:
            stage('Releasing the GPU...')
            r = subprocess.run([colab, 'stop', '-s', session], stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, env=_env())
            if r.returncode and allocated:
                log(f'WARNING: "colab stop -s {session}" failed; check "colab sessions":\n{r.stdout}{r.stderr}')


def main():
    ap = argparse.ArgumentParser(description='Convert an EPUB to an .m4b audiobook with audiblez on a Colab GPU.')
    ap.add_argument('-l', '--lang', choices=sorted(VOICES), default='zh',
                    help='zh: Mandarin (Qwen3-TTS clone of voices/vivian_calm.wav on a G4, Kokoro v1.1-zh zf_001 on '
                         'an L4/T4), en: American English (Kokoro af_heart); default zh')
    ap.add_argument('-s', '--speed', type=float, default=1.0,
                    help='speed from 0.5 to 2.0, Kokoro voices only (default 1.0)')
    ap.add_argument('--gpus', default=','.join(GPUS),
                    help=f'GPUs to try, in order (default {",".join(GPUS)}); e.g. --gpus T4 to test a smaller GPU')
    ap.add_argument('epub')
    args = ap.parse_args()
    if not os.path.isfile(args.epub):
        ap.error(f'no such file: {args.epub}')
    sys.stdout.reconfigure(line_buffering=True)  # show progress even when output is redirected
    show = lambda frac, msg: msg.startswith('Progress') and print(msg, end='\r', flush=True)
    try:
        m4b = convert(os.path.abspath(args.epub), args.lang, args.speed, gpus=args.gpus.split(','),
                      session=f'audiblez-{os.getpid()}', progress=show)
    except ColabError as e:
        sys.exit(f'error: {e}')
    print(f'Done: {m4b}')


if __name__ == '__main__':
    main()
