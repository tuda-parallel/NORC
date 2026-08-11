# This file is part of the NORC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import os
from copy import copy

from PySide6.QtWidgets import QFileDialog, QMessageBox, QMainWindow, QCheckBox, QStyle, QProgressDialog, QApplication
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt
import matplotlib

from norc.helpers.util import experiment_filter, available_measurements, open_experiment_source
from norc.ui.examine_tab import examine_tab
from norc.ui.ratings_tab import ratings_tab
from norc.ui.ranking_tab import ranking_tab
from norc.ui.generate_dialog import generate_dialog
from norc.core.analyze import analyze_experiment
from norc.ui.ui_util import add_v_spacer, clear_widget


class main_window(QMainWindow):
    def __init__(self, appstate):
        super().__init__()
        self.appstate = appstate
        self.ui = appstate.load_ui("mainwindow.ui")
        self.ui.tw_modes.addTab(ratings_tab(appstate), "Ratings")
        self.ui.tw_modes.addTab(examine_tab(appstate), "Examine")
        self.ui.tw_modes.addTab(ranking_tab(appstate), "Ranking")

        self.filter_boxes = {"benchmark": [], "system": [], "noise": [], "counter": []}
        self._filtering_in_progress = False

        self.ui.sb_thr_contrib.setValue(1)
        self.ui.sb_thr_visits.setValue(100)

        # Populate colormap selector
        self.ui.cb_colormap.currentTextChanged.connect(appstate.plt_mgr.set_colormap)

        self.ui.cb_plotmode.currentTextChanged.connect(self.update_config)
        self.ui.sb_colorbands.editingFinished.connect(self.update_config)
        self.ui.sb_thr_contrib.editingFinished.connect(self.update_config)
        self.ui.sb_thr_visits.editingFinished.connect(self.update_config)

        # Freedesktop icon themes (set via `iconset theme=` in the .ui file) aren't
        # available on all platforms (e.g. Windows), so fall back to Qt's built-in
        # standard icons whenever the theme lookup comes back empty.
        style = self.style()
        if self.ui.action_open.icon().isNull():
            self.ui.action_open.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        if self.ui.action_open_zip.icon().isNull():
            self.ui.action_open_zip.setIcon(style.standardIcon(QStyle.SP_DriveHDIcon))

        self.ui.action_open.triggered.connect(self.open_experiment_folder_dialog)
        self.ui.action_open_zip.triggered.connect(self.open_experiment_zip_dialog)
        self.ui.actionCreate_Measurement_Runner.triggered.connect(self.open_generate_dialog)

        # Grouping UI
        self.ui.cb_lump_benchmark.stateChanged.connect(self.update_config)
        self.ui.cb_lump_system.stateChanged.connect(self.update_config)
        self.ui.cb_lump_resources.stateChanged.connect(self.update_config)
        self.ui.cb_lump_params.stateChanged.connect(self.update_config)
        self.ui.cb_lump_noise.stateChanged.connect(self.update_config)

        self.update_config()

        self.ui.btn_flt_select_all.clicked.connect(lambda: self.set_current_filters_checked(True))
        self.ui.btn_flt_deselect_all.clicked.connect(lambda: self.set_current_filters_checked(False))

        self.update_filter_ui()
        self.appstate.plt_mgr.reconfigured.connect(self.update_filter_ui)

        self.ui.show()

    def update_config(self):
        # Each set_* below can independently emit plt_mgr.reconfigured, which
        # would otherwise re-run every reconfigured slot (e.g. score_tab's
        # compute_scores) once per setter instead of once for the whole batch.
        # Block those emits and fire a single one after all settings landed.
        self.appstate.plt_mgr.blockSignals(True)
        try:
            self.appstate.plt_mgr.set_plotmode(self.ui.cb_plotmode.currentText())
            self.appstate.plt_mgr.set_colorbands(self.ui.sb_colorbands.value())
            self.appstate.plt_mgr.set_contribution_threshold(self.ui.sb_thr_contrib.value())
            self.appstate.plt_mgr.set_visit_threshold(self.ui.sb_thr_visits.value())

            self.appstate.plt_mgr.set_parameter_groupings(
                benchmark=self.ui.cb_lump_benchmark.checkState() == Qt.Checked,
                system=self.ui.cb_lump_system.checkState() == Qt.Checked,
                resources=self.ui.cb_lump_resources.checkState() == Qt.Checked,
                params=self.ui.cb_lump_params.checkState() == Qt.Checked,
                noise=self.ui.cb_lump_noise.checkState() == Qt.Checked,
            )
        finally:
            self.appstate.plt_mgr.blockSignals(False)
        self.appstate.plt_mgr.reconfigured.emit()

    def open_experiment_folder_dialog(self):
        dialog = QFileDialog(self.ui)
        dialog.setFileMode(QFileDialog.Directory)
        self._open_experiment_from_dialog(dialog)

    def open_experiment_zip_dialog(self):
        dialog = QFileDialog(self.ui)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("Zip archives (*.zip)")
        self._open_experiment_from_dialog(dialog)

    def _open_experiment_from_dialog(self, dialog):
        if dialog.exec():
            selected = dialog.selectedFiles()[0]
            try:
                # Only used to validate the selection; closed before analyze_experiment
                # and plt_mgr.open_experiment (which open their own handles) run, so we
                # never have more than one handle on the same zip archive open at once.
                with open_experiment_source(selected, read_only=True) as tree:
                    has_result = tree.isdir(os.path.join(tree.root, "result"))
                    has_deviations = has_result and tree.isdir(os.path.join(tree.root, "result", ".deviations"))
            except FileNotFoundError as e:
                dlg = QMessageBox(self)
                dlg.setText(str(e))
                dlg.exec()
                return

            if not has_result:
                dlg = QMessageBox(self)
                dlg.setText("The selected experiment does not contain a result.")
                dlg.exec()
                return
            if not has_deviations:
                dlg = QMessageBox(self)
                dlg.setText(
                    "A measurement result was found but no deviations are present.\nCalculate them now (may take a while)?"
                )
                dlg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                resp = dlg.exec()
                if resp == QMessageBox.Yes:
                    if not self._calculate_deviations(selected):
                        return
                else:
                    return

            self.appstate.plt_mgr.open_experiment(selected)

        self.update_config()

    def _calculate_deviations(self, experiment_root):
        """Run the deviation calculation while showing a modal progress window.

        The calculation runs on the GUI thread; the event loop is pumped after
        each measurement (via the progress callback) so the dialog stays
        responsive and the bar advances. Returns True on success, or False if
        the calculation failed, in which case an error is shown and any partial
        output has already been cleaned up by analyze_experiment.
        """
        progress = QProgressDialog(self.ui)
        progress.setWindowTitle("Analyzing experiment")
        progress.setLabelText("Calculating deviations…")
        # analyze_experiment has no safe mid-run cancellation point, so don't offer one.
        progress.setCancelButton(None)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        # Show a busy indicator until the first callback reports the measurement count.
        progress.setRange(0, 0)
        progress.show()

        def on_progress(done, total):
            progress.setMaximum(total)
            progress.setValue(done)
            progress.setLabelText(f"Calculating deviations… ({done}/{total} measurements)")
            QApplication.processEvents()

        error = None
        try:
            analyze_experiment(experiment_root, progress_callback=on_progress)
        except Exception as e:
            error = str(e)
        progress.close()

        if error is not None:
            dlg = QMessageBox(self)
            dlg.setIcon(QMessageBox.Critical)
            dlg.setText(f"Deviation calculation failed:\n{error}")
            dlg.exec()
            return False
        return True

    def open_generate_dialog(self):
        # No experiment needs to be open: generate_dialog also supports
        # selecting counters from an MQM selected_counters.json instead of
        # NORC's resilience analysis, which needs no experiment_root.
        dialog = generate_dialog(self.appstate, self)
        dialog.exec()

    # experiment_filter treats an empty filter string as "accept everything",
    # since that's also what it means when no filter was specified at all
    # (e.g. from the CLI). That makes "" ambiguous with "the user unchecked
    # every box", which would otherwise show everything instead of nothing.
    # Use a sentinel that can't match any real dimension value to represent
    # that case explicitly.
    _NONE_SELECTED = "\x00none-selected\x00"

    def _build_filter_string(self, key):
        boxes = self.filter_boxes[key]
        checked = [cb.text() for cb in boxes if cb.isChecked()]
        if boxes and not checked:
            return self._NONE_SELECTED
        return ",".join(checked)

    def apply_filters(self):
        if self._filtering_in_progress:
            return
        self._filtering_in_progress = True

        benchmarks = self._build_filter_string("benchmark")
        systems = self._build_filter_string("system")
        noises = self._build_filter_string("noise")
        metrics = self._build_filter_string("counter")

        self.appstate.plt_mgr.set_filter(
            experiment_filter(benchmarks, systems, noises, metrics)
        )
        self._filtering_in_progress = False

    def set_current_filters_checked(self, checked):
        page_to_key = {
            self.ui.pg_flt_benchmark: "benchmark",
            self.ui.pg_flt_system: "system",
            self.ui.pg_flt_noise: "noise",
            self.ui.pg_flt_metric: "counter",
        }
        key = page_to_key.get(self.ui.tb_filters.currentWidget())
        if key is None:
            return
        # Setting each checkbox individually would fire apply_filters() per
        # checkbox, and that in turn triggers update_filter_ui() (via the
        # plt_mgr.reconfigured signal), which tears down and rebuilds this
        # very list of checkboxes mid-loop. Block signals and apply once at
        # the end instead.
        try:
            for cb in self.filter_boxes[key]:
                cb.blockSignals(True)
            for cb in self.filter_boxes[key]:
                cb.setChecked(checked)
            QApplication.processEvents()
        finally:
            for cb in self.filter_boxes[key]:
                cb.blockSignals(False)
        self.apply_filters()

    def update_filter_ui(self):
        plt_mgr = self.appstate.plt_mgr

        # Create a copy of the current selection with a no-op filter to see what's theoretically available.
        sel = copy(plt_mgr.plot_settings.selection)
        sel.filter = experiment_filter()
        sel.lump_benchmarks = False
        sel.lump_systems = False
        sel.lump_noise = False

        for l in self.filter_boxes.values():
            for cb in l:
                cb.deleteLater()

        self.filter_boxes = {"benchmark": [], "system": [], "noise": [], "counter": []}

        # Check if there is anything to load
        tree = plt_mgr.plot_settings.tree
        if tree is None:
            return
        deviation_dir = os.path.join(tree.root, "result", ".deviations")
        if not tree.isdir(deviation_dir):
            return

        # Get all available plot infos
        benchmarks = set()
        systems = set()
        noises = set()
        metrics = set()

        for inf in available_measurements(tree, deviation_dir, sel).values():
            benchmarks.add(inf.benchmark)
            systems.add(inf.system)
            noises.add(inf.noise_pattern)
            metrics.add(inf.counter)

        # Special noise patterns are always permitted by filters
        noises.discard("NO_NOISE")
        noises.discard("ALL_NOISE")

        clear_widget(self.ui.pg_flt_benchmark)
        clear_widget(self.ui.pg_flt_system)
        clear_widget(self.ui.pg_flt_noise)
        clear_widget(self.ui.pg_flt_metric)

        self.ui.pg_flt_benchmark.setVisible(len(benchmarks) > 1)
        self.ui.pg_flt_system.setVisible(len(systems) > 1)
        self.ui.pg_flt_noise.setVisible(len(noises) > 1)
        self.ui.pg_flt_metric.setVisible(len(metrics) > 1)

        for it in sorted(list(benchmarks)):
            cb = QCheckBox(it, self)
            cb.setChecked(plt_mgr.plot_settings.selection.filter.flt_benchmark(it))
            cb.stateChanged.connect(self.apply_filters)
            self.ui.pg_flt_benchmark.layout().addWidget(cb)
            self.filter_boxes["benchmark"].append(cb)

        for it in sorted(list(systems)):
            cb = QCheckBox(it, self)
            cb.setChecked(plt_mgr.plot_settings.selection.filter.flt_system(it))
            cb.stateChanged.connect(self.apply_filters)
            self.ui.pg_flt_system.layout().addWidget(cb)
            self.filter_boxes["system"].append(cb)

        for it in sorted(list(noises)):
            cb = QCheckBox(it, self)
            cb.setChecked(plt_mgr.plot_settings.selection.filter.flt_noise(it))
            cb.stateChanged.connect(self.apply_filters)
            self.ui.pg_flt_noise.layout().addWidget(cb)
            self.filter_boxes["noise"].append(cb)

        for it in sorted(list(metrics)):
            cb = QCheckBox(it, self)
            cb.setChecked(plt_mgr.plot_settings.selection.filter.flt_counter(it))
            cb.stateChanged.connect(self.apply_filters)
            self.ui.pg_flt_metric.layout().addWidget(cb)
            self.filter_boxes["counter"].append(cb)

        add_v_spacer(self.ui.pg_flt_benchmark)
        add_v_spacer(self.ui.pg_flt_system)
        add_v_spacer(self.ui.pg_flt_noise)
        add_v_spacer(self.ui.pg_flt_metric)
