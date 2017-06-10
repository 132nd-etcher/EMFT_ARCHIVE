# coding=utf-8

import os

from src.cfg.cfg import Config
from src.global_ import MAIN_UI
from src.misc import appveyor, downloader, github_old
from src.misc.fs import saved_games_path
from src.miz.miz import Miz
from src.ui.base import GroupBox, HLayout, VLayout, PushButton, Radio, Checkbox, Label, Combo, GridLayout, box_question, \
    BrowseDialog, LineEdit
from src.ui.main_ui_interface import I
from src.ui.main_ui_tab_widget import MainUiTabChild
from src.utils.custom_logging import make_logger
from src.utils.custom_path import Path
from .dialog_profile_editor import DialogProfileEditor
from .tab_reorder_adapter import TabReorderAdapter, TAB_NAME
from ..finder.find_local_profile import FindLocalProfile
from src.reorder.service import ChangeActiveProfile
from src.reorder.value import ACTIVE_PROFILE

try:
    import winreg
except ImportError:
    from unittest.mock import MagicMock

    winreg = MagicMock()

logger = make_logger(__name__)


class TabChildReorder(MainUiTabChild, TabReorderAdapter):
    def tab_reorder_change_active_profile(self, new_profile_name):
        self.profile_combo.set_index_from_text(new_profile_name)

    def tab_clicked(self):
        self.scan_artifacts()

    @property
    def tab_title(self):
        return TAB_NAME

    def __init__(self, parent=None):
        MainUiTabChild.__init__(self, parent=parent)

        self.manual_group = GroupBox()

        self.single_miz_lineedit = LineEdit('', read_only=True)

        self.manual_output_folder_lineedit = LineEdit('', read_only=True)

        self.auto_src_le = LineEdit('', read_only=True)

        self.auto_scan_label_result = Label('')
        self.auto_scan_combo_branch = Combo(self._on_branch_changed, list())

        self.auto_out_le = LineEdit('', read_only=True)

        self._remote = None

        self.check_skip_options = Checkbox(
            'Skip "options" file: the "options" file at the root of the MIZ is player-specific, and is of very relative'
            ' import for the MIZ file itself. To avoid having irrelevant changes in the SCM, it can be safely skipped'
            ' during reordering.',
            self.toggle_skip_options
        )

        self.radio_single = Radio('Manual mode', self.on_radio_toggle)
        self.radio_auto = Radio('Automatic mode', self.on_radio_toggle)

        self.profile_combo = Combo(self._on_profile_change, FindLocalProfile.get_all_profiles_names())
        self.profile_new_btn = PushButton('New', self._on_new_profile, self)
        self.profile_edit_btn = PushButton('Edit', self._on_edit_profile, self)

        self.setLayout(
            VLayout(
                [
                    Label(
                        'By design, LUA tables are unordered, which makes tracking changes extremely difficult.\n\n'
                        'This lets you reorder them alphabetically before you push them in a SCM.\n\n'
                        'It is recommended to set the "Output folder" to your local SCM repository.'
                    ), 20,
                    GroupBox(
                        'Options',
                        VLayout(
                            [
                                self.check_skip_options,
                            ],
                        )
                    ), 20,
                    GroupBox(
                        'MIZ file reordering',
                        GridLayout(
                            [
                                [
                                    (self.radio_single, dict(span=(1, -1))),
                                ],
                                [
                                    Label('Source MIZ'),
                                    self.single_miz_lineedit,
                                    PushButton('Browse', self.manual_browse_for_miz, self),
                                    PushButton('Open', self.manual_open_miz, self),
                                ],
                                [
                                    Label('Output folder'),
                                    self.manual_output_folder_lineedit,
                                    PushButton('Browse', self.manual_browse_for_output_folder, self),
                                    PushButton('Open', self.manual_open_output_folder, self),
                                ],
                                [
                                    (self.radio_auto, dict(span=(1, -1))),
                                ],
                                [
                                    Label('Profile'),
                                    self.profile_combo,
                                    self.profile_new_btn,
                                    self.profile_edit_btn,
                                ],
                                [
                                    Label('Source folder'),
                                    self.auto_src_le,
                                    PushButton('Open', self.auto_src_open, self),
                                ],
                                [
                                    Label('Output folder'),
                                    self.auto_out_le,
                                    PushButton('Open', self.auto_out_open, self),
                                ],
                                [
                                    Label('Branch filter'),
                                    HLayout(
                                        [
                                            self.auto_scan_combo_branch,
                                            self.auto_scan_label_result,
                                        ],
                                    ),
                                    PushButton('Refresh', self.scan_artifacts, self),
                                    PushButton('Download', self.auto_download, self)
                                ],
                            ],
                        ),
                    ), 20,
                    PushButton(
                        text='Reorder MIZ file',
                        func=self.reorder_miz,
                        parent=self,
                        min_height=40,
                    ),
                ],
                set_stretch=[(4, 2)]
            )
        )
        self._initialize_config_values()
        # self.scan_branches()
        # self.scan_artifacts()
        self.initial_scan()

    def _on_new_profile(self):
        dialog = DialogProfileEditor()
        dialog.exec()

    def _on_edit_profile(self):
        dialog = DialogProfileEditor.from_profile(self.profile_combo.currentText())
        dialog.exec()
        self._load_values_from_profile()

    def _on_profile_change(self, selected_profile_name):
        ChangeActiveProfile.change_active_profile(selected_profile_name)
        self._load_values_from_profile()

    def _load_values_from_profile(self):
        if ACTIVE_PROFILE:
            self.auto_src_le.setText(ACTIVE_PROFILE.src_folder)
            self.auto_out_le.setText(ACTIVE_PROFILE.output_folder)

    def _initialize_config_values(self):
        """Retrieves values from config files to initialize the UI"""

        def check_folder(folder: str, target: LineEdit):
            """
            Verify that a folder exists, and set the value tot he corresponding GUI control
            :param folder: folder as a string
            :param target: LineEdit to update if the value is correct
            """
            p = Path(folder)
            if not p.exists():
                logger.error(f'path does not exist: {p.abspath()}')
            elif not p.isdir():
                logger.error(f'not a directory: {p.abspath()}')
            else:
                target.setText(str(p.abspath()))

        if Config().reorder_last_profile_name:
            self.profile_combo.set_index_from_text(Config().reorder_last_profile_name)
            self._load_values_from_profile()

        self.radio_single.setChecked(not Config().auto_mode)
        self.radio_auto.setChecked(Config().auto_mode)
        self.check_skip_options.setChecked(Config().skip_options_file)

        if Config().single_miz_last:
            p = Path(Config().single_miz_last)
            if p.exists() and p.isfile() and p.ext == '.miz':
                self.single_miz_lineedit.setText(str(p.abspath()))

        if Config().single_miz_output_folder:
            check_folder(Config().single_miz_output_folder, self.manual_output_folder_lineedit)

    @property
    def manual_miz_path(self) -> Path:
        t = self.single_miz_lineedit.text()
        if len(t) > 3:
            return Path(t)

    @property
    def manual_output_folder_path(self) -> Path:
        t = self.manual_output_folder_lineedit.text()
        if len(t) > 3:
            return Path(t)

    def manual_open_miz(self):
        if self.manual_miz_path and self.manual_miz_path.exists():
            os.startfile(self.manual_miz_path.dirname())

    def manual_browse_for_miz(self):
        if Config().single_miz_last:
            init_dir = Path(Config().single_miz_last).dirname()
        else:
            init_dir = saved_games_path.abspath()
        p = BrowseDialog.get_existing_file(
            self, 'Select MIZ file', filter_=['*.miz'], init_dir=init_dir)
        if p:
            p = Path(p)
            self.single_miz_lineedit.setText(p.abspath())
            Config().single_miz_last = p.abspath()

    def manual_open_output_folder(self):
        if self.manual_output_folder_path and self.manual_output_folder_path.exists():
            os.startfile(self.manual_output_folder_path)

    def manual_browse_for_output_folder(self):
        if self.manual_output_folder_path:
            init_dir = self.manual_output_folder_path.dirname()
        elif self.manual_miz_path:
            init_dir = self.manual_miz_path.dirname()
        else:
            init_dir = Path('.')
        p = BrowseDialog.get_directory(self, 'Select output directory', init_dir=init_dir.abspath())
        if p:
            p = Path(p)
            self.manual_output_folder_lineedit.setText(p.abspath())
            Config().single_miz_output_folder = p.abspath()

    def auto_out_open(self):
        if self.auto_out_path.exists():
            os.startfile(str(self.auto_out_path))

    @property
    def auto_out_path(self) -> Path or None:
        t = self.auto_out_le.text()
        if len(t) > 3:
            return Path(t)
        return None

    @property
    def auto_src_path(self) -> Path or None:
        t = self.auto_src_le.text()
        if len(t) > 3:
            return Path(t)
        return None

    def auto_src_open(self):
        if self.auto_src_path:
            os.startfile(str(self.auto_src_path.abspath()))

    def toggle_skip_options(self, *_):
        Config().skip_options_file = self.check_skip_options.isChecked()

    def on_radio_toggle(self, *_):
        Config().auto_mode = self.radio_auto.isChecked()

    @property
    def skip_options_file_is_checked(self) -> bool:
        return self.check_skip_options.isChecked()

    @staticmethod
    def _on_reorder_error(miz_file):
        # noinspection PyCallByClass
        I.error(f'Could not unzip the following file:\n\n{miz_file}\n\n'
                'Please check the log, and eventually send it to me along with the MIZ file '
                'if you think this is a bug.')

    def _reorder_auto(self):

        error = None

        if not self.remote:
            error = 'no remote file found'

        local_file = self._look_for_local_file(self.remote.version)

        if local_file is None:
            error = f'no local file found for version: {self.remote.version}'
        elif not local_file.isfile():
            error = f'not a file: {local_file.abspath()}'
        elif not self.auto_out_path:
            error = 'no output folder selected'

        if error:
            logger.error(error)
            MAIN_UI.msg(error.capitalize())
            return

        self._reorder_miz(local_file, self.auto_out_path, self.skip_options_file_is_checked)

    def _reorder_manual(self):
        error = None
        if not self.manual_miz_path:
            error = 'no MIZ file selected'
        elif not self.manual_output_folder_path:
            error = 'no output folder selected'
        elif not self.manual_miz_path.exists():
            error = f'file not found: {self.manual_miz_path.abspath()}'
        elif not self.manual_miz_path.isfile():
            error = f'not a file: {self.manual_miz_path.abspath()}'

        if error:
            logger.error(error)
            MAIN_UI.msg(error.capitalize())
            return

        self._reorder_miz(self.manual_miz_path, self.manual_output_folder_path, self.skip_options_file_is_checked)

    def reorder_miz(self):
        if self.radio_auto.isChecked():
            self._reorder_auto()
        else:
            self._reorder_manual()

    def _reorder_miz(self, miz_file, output_dir, skip_options_file):
        if miz_file:
            self.main_ui.pool.queue_task(
                Miz.reorder,
                [
                    miz_file,
                    output_dir,
                    skip_options_file,
                ],
                _err_callback=self._on_reorder_error,
                _err_args=[miz_file],
            )
        else:
            MAIN_UI.msg('Local file not found for version: {}\n\n'
                        'Download it first!'.format(self.remote.version))

    @property
    def selected_branch(self):
        return self.auto_scan_combo_branch.currentText()

    def _on_branch_changed(self):
        Config().reorder_selected_auto_branch = self.selected_branch
        self.scan_artifacts()

    def tab_reorder_update_view_after_branches_scan(self, *_):

        try:
            self.auto_scan_combo_branch.set_index_from_text(Config().reorder_selected_auto_branch)
        except ValueError:
            MAIN_UI.msg('Selected branch has been deleted from the remote:\n\n{}'.format(
                Config().reorder_selected_auto_branch))
            self.auto_scan_combo_branch.setCurrentIndex(0)

    def tab_reorder_update_view_after_artifact_scan(self, *_):

        if self.remote:

            if isinstance(self.remote, str):
                # The scan returned an error message
                msg, color = self.remote, 'red'

            else:

                # self.auto_scan_label_result.setText('{} ({})'.format(self.remote.version, self.remote.branch))
                logger.debug('latest remote version found: {}'.format(self.remote.version))
                local_trmt_path = self._look_for_local_file(self.remote.version)
                if local_trmt_path:
                    msg, color = '{}: you have the latest version'.format(self.remote.version), 'green'
                    logger.debug(msg)
                    self.auto_scan_label_result.setText(msg)
                else:
                    msg, color = '{}: new version found'.format(self.remote.version), 'orange'
                    logger.debug(msg)
        else:
            msg, color = 'error while probing remote, see log', 'red'

        self.auto_scan_label_result.setText(msg)
        self.auto_scan_label_result.set_text_color(color)

    def _look_for_local_file(self, version) -> Path:
        logger.debug('probing local file system')
        if self.auto_src_path:
            p = Path(self.auto_src_path).joinpath('TRMT_{}.miz'.format(version))
            if p.exists():
                logger.debug(f'local TRMT found: {p.abspath()}')
                return p
            else:
                logger.warning('no local MIZ file found with version: {}'.format(self.remote.version))

    def _initial_scan(self):
        self.tab_reorder_update_view_after_artifact_scan(self._scan_branches())
        self._scan_artifacts()

    def initial_scan(self):
        self.main_ui.pool.queue_task(self._initial_scan)

    def _scan_branches(self):
        logger.debug('probing GH for remote branches list')
        remote_branches = github_old.get_available_branches()
        logger.debug(f'remote branches found: {remote_branches}')
        remote_branches.remove('master')
        remote_branches.remove('develop')
        self.auto_scan_combo_branch.reset_values(
            ['All', 'master', 'develop'] + sorted(remote_branches)
        )

    def scan_branches(self, *_):
        """Queues a refresh of the remote branches found on Github"""
        self.main_ui.pool.queue_task(
            task=self._scan_branches,
            _task_callback=I.tab_reorder_update_view_after_branches_scan
        )

    def _scan_artifacts(self):
        logger.debug('scanning for artifacts')
        if not self.selected_branch:
            logger.error('no branch selected')
            self._remote = None
        else:
            # noinspection PyBroadException
            try:
                self._remote = appveyor.get_latest_remote_version(self.selected_branch)
            except:
                logger.exception('error while scanning for artifacts')
                self._remote = None

    def scan_artifacts(self, *_):
        self.auto_scan_label_result.set_text_color('black')
        self.auto_scan_label_result.setText('Probing...')
        self.main_ui.pool.queue_task(
            task=self._scan_artifacts,
            _task_callback=I.tab_reorder_update_view_after_artifact_scan)

    @property
    def remote(self) -> appveyor.AVResult:
        return self._remote

    def auto_download(self):

        if self.remote and not isinstance(self.remote, str):
            local_file = Path(self.auto_src_path).joinpath(self.remote.file_name).abspath()

            if local_file.exists():
                if not box_question(self, 'Local file already exists; do you want to overwrite?'):
                    return

            MAIN_UI.progress_start(
                'Downloading {}'.format(self.remote.download_url.split('/').pop()),
                length=100,
                label=self.remote.file_name
            )

            self.main_ui.pool.queue_task(
                downloader.download,
                kwargs=dict(
                    url=self.remote.download_url,
                    local_file=local_file,
                    file_size=self.remote.file_size
                ),
                _task_callback=self.scan_artifacts
            )