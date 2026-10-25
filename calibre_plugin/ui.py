import os
import shutil
import tempfile
from functools import partial

from qt.core import QApplication, QIcon, QPixmap, Qt

from calibre.gui2 import Dispatcher, error_dialog, is_dark_theme
from calibre.gui2.actions import InterfaceAction
from calibre.gui2.threaded_jobs import ThreadedJob
from calibre_plugins.audiblez_audiobook.colab_audiblez import ColabError, convert, find_colab

# Calibre stores languages as ISO 639-2 codes; colab_audiblez takes zh|en.
LANGS = {'zho': 'zh', 'eng': 'en'}


def run_job(book_id, lang, epub, payload, log=None, abort=None, notifications=None):
    return convert(epub, lang, payload=payload, session=f'audiblez-{book_id}', log=log, abort=abort,
                   progress=lambda frac, msg: notifications.put((frac, msg)))


class AudiobookAction(InterfaceAction):
    name = 'Audiblez Audiobook'
    action_spec = ('Convert to audiobook', None, 'Convert the selected books to M4B audiobooks on a Colab GPU', None)
    action_type = 'current'

    def genesis(self):
        self.qaction.setIcon(self.audiobook_icon())
        app = QApplication.instance()
        if hasattr(app, 'palette_changed'):  # calibre's signal for switching between light and dark
            app.palette_changed.connect(lambda: self.qaction.setIcon(self.audiobook_icon()))
        self.qaction.triggered.connect(self.convert_selected)

    def audiobook_icon(self):
        # The toolbar button and the right-click menu share this action, so the icon holds both drawings at their own
        # pixel sizes and Qt picks the closest: the plain headphones in menus (16 pt), headphones and book in the bar.
        theme = 'dark' if is_dark_theme() else 'light'
        names = [f'images/menu-{theme}-{size}.png' for size in (16, 32)] + \
                [f'images/toolbar-{theme}-{size}.png' for size in (64, 96, 128, 192)]
        icon = QIcon()
        for data in self.load_resources(names).values():
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            icon.addPixmap(pixmap)
        return icon

    def convert_selected(self):
        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            find_colab()
        except ColabError as e:
            return error_dialog(self.gui, 'Colab CLI not ready', str(e), show=True)
        finally:
            QApplication.restoreOverrideCursor()

        # Our audiblez and its reference voices, uploaded to the VM by convert() (built by build_plugin.py)
        payload_zip = self.load_resources(['audiblez_payload.zip'])['audiblez_payload.zip']
        db = self.gui.current_db.new_api
        skipped = []
        for book_id in map(self.gui.library_view.model().id, rows):
            title = db.field_for('title', book_id)
            lang = next((LANGS[c] for c in db.field_for('languages', book_id) if c in LANGS), None)
            if lang is None or not db.has_format(book_id, 'EPUB'):
                skipped.append(title)
                continue
            # Work in a temp dir: the .m4b is written next to the EPUB it is made from.
            workdir = tempfile.mkdtemp(prefix='audiblez_')
            epub = os.path.join(workdir, 'book.epub')
            db.copy_format_to(book_id, 'EPUB', epub)
            payload = os.path.join(workdir, 'audiblez_payload.zip')
            with open(payload, 'wb') as f:
                f.write(payload_zip)
            job = ThreadedJob('audiblez_audiobook', f'Audiobook: {title}', run_job, (book_id, lang, epub, payload), {},
                              Dispatcher(partial(self.done, book_id, workdir)))
            self.gui.job_manager.run_threaded_job(job)
        if skipped:
            error_dialog(self.gui, 'Cannot convert to audiobook',
                         'These books need an EPUB format and their language set to Chinese or English.',
                         det_msg='\n'.join(skipped), show=True)

    def done(self, book_id, workdir, job):
        try:
            if job.failed:
                return self.gui.job_exception(job, dialog_title='Audiobook conversion failed')
            self.gui.current_db.new_api.add_format(book_id, 'M4B', job.result)
            self.gui.library_view.model().refresh_ids([book_id])
            self.gui.status_bar.show_message(f'Audiobook added: {job.description}', 5000)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
