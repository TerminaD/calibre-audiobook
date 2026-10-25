from calibre.customize import InterfaceActionBase


class AudiblezAudiobook(InterfaceActionBase):
    name = 'Audiblez Audiobook'
    description = ('Convert the selected books to M4B audiobooks with audiblez on a Google Colab GPU '
                   '(Chinese: Qwen3-TTS voice clone on a G4, Kokoro v1.1-zh on an L4/T4; English: Kokoro)')
    supported_platforms = ['osx', 'linux']
    author = 'termina'
    version = (2, 0, 0)
    minimum_calibre_version = (6, 0, 0)
    actual_plugin = 'calibre_plugins.audiblez_audiobook.ui:AudiobookAction'
