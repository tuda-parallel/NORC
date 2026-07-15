# This file is part of the NORC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import os
from copy import copy

from PySide6.QtWidgets import QFileDialog, QMessageBox, QMainWindow, QCheckBox, QStyle
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt
import matplotlib

from norc.helpers.util import experiment_filter, available_measurements, open_experiment_source
from norc.ui.examine_tab import examine_tab
from norc.ui.ratings_tab import ratings_tab
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

        self.update_filter_ui()
        self.appstate.plt_mgr.reconfigured.connect(self.update_filter_ui)

        self.ui.show()

    def update_config(self):
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
                with open_experiment_source(selected) as tree:
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
                    analyze_experiment(selected)
                else:
                    return

            self.appstate.plt_mgr.open_experiment(selected)

        self.update_config()

    def open_generate_dialog(self):
        if not self.appstate.plt_mgr.experiment_root:
            dlg = QMessageBox(self)
            dlg.setText("Please open an experiment before creating a measurement runner.")
            dlg.exec()
            return

        dialog = generate_dialog(self.appstate, self)
        dialog.exec()

    def apply_filters(self):
        if self._filtering_in_progress:
            return
        self._filtering_in_progress = True
        benchmarks = ""
        systems = ""
        noises = ""
        metrics = ""

        for cb in self.filter_boxes["benchmark"]:
            if cb.isChecked():
                benchmarks += f"{cb.text()},"
        for cb in self.filter_boxes["system"]:
            if cb.isChecked():
                systems += f"{cb.text()},"
        for cb in self.filter_boxes["noise"]:
            if cb.isChecked():
                noises += f"{cb.text()},"
        for cb in self.filter_boxes["counter"]:
            if cb.isChecked():
                metrics += f"{cb.text()},"

        self.appstate.plt_mgr.set_filter(
            experiment_filter(benchmarks, systems, noises, metrics)
        )
        self._filtering_in_progress = False

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
