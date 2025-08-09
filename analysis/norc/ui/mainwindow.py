# This file is part of the NORC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import os
from copy import copy

from PySide6.QtWidgets import QFileDialog, QMessageBox, QMainWindow, QCheckBox
from PySide6.QtCore import Qt

from norc.helpers.util import experiment_filter, available_measurements
from norc.ui.examine_tab import examine_tab
from norc.ui.ratings_tab import ratings_tab
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

        self.ui.cb_plotmode.currentTextChanged.connect(self.update_config)
        self.ui.sb_colorbands.editingFinished.connect(self.update_config)
        self.ui.sb_thr_contrib.editingFinished.connect(self.update_config)
        self.ui.sb_thr_visits.editingFinished.connect(self.update_config)

        self.ui.action_open.triggered.connect(self.open_experiment_dialog)

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

    def open_experiment_dialog(self):
        dialog = QFileDialog(self.ui)
        dialog.setFileMode(QFileDialog.Directory)
        if dialog.exec():
            exdir = dialog.selectedFiles()[0]
            if not os.path.isdir(os.path.join(exdir, "result")):
                dlg = QMessageBox(self)
                dlg.setText("The selected directory does not contain a result.")
                dlg.exec()
                return
            if not os.path.isdir(os.path.join(exdir, "result", ".deviations")):
                dlg = QMessageBox(self)
                dlg.setText(
                    "A measurement result was found but no deviations are present.\nCalculate them now (may take a while)?"
                )
                dlg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                resp = dlg.exec()
                if resp == QMessageBox.Yes:
                    analyze_experiment(exdir)
                else:
                    return

            self.appstate.plt_mgr.open_experiment(exdir)

        self.update_config()

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
        deviation_dir = os.path.join(plt_mgr.experiment_root, "result", ".deviations")
        if not os.path.exists(deviation_dir):
            return

        # Get all available plot infos
        benchmarks = set()
        systems = set()
        noises = set()
        metrics = set()

        for inf in available_measurements(deviation_dir, sel).values():
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
