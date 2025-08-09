# This file is part of the NORC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import matplotlib

matplotlib.use("QtAgg")

from PySide6.QtCore import Signal
from PySide6.QtGui import Qt, QColor
from PySide6.QtWidgets import (
    QWidget,
    QSplitter,
    QVBoxLayout,
    QFormLayout,
    QComboBox,
    QLabel,
    QSizePolicy,
)

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT as FigNavigation,
)

from norc.ui.qt_utils import update_choices
from norc.ui.ui_util import score_color
import norc.helpers.util as util
import norc.core.plot_rel_dev as prd
import norc.core.score as scr
from norc.core.plotmanager import PlotManager


class chart_controls(QWidget):
    selection_changed = Signal()

    def __init__(self, parent, plt_mgr: PlotManager):
        super().__init__(parent)

        self.parent = parent

        self.plt_mgr = plt_mgr
        self.score = None

        # This is not a lock for thread safety. It merely prevents update loops between UI and configuration within the same thread.
        self.currently_updating_ = False

        self.setLayout(QVBoxLayout(self))
        self.layout().addWidget(FigNavigation(parent.canvas, self))
        self.layout().addWidget(QWidget(self))

        self.plot_info = util.measurement_info()
        self.plot_settings = prd.plot_settings()

        selection_container = QWidget(self)
        self.layout().addWidget(selection_container)
        selection_container.setLayout(QFormLayout(selection_container))
        form = selection_container.layout()

        self.cb_benchmark = QComboBox(selection_container)
        form.addRow(QLabel("Benchmark"), self.cb_benchmark)

        self.cb_system = QComboBox(selection_container)
        form.addRow(QLabel("System"), self.cb_system)

        self.cb_noise = QComboBox(selection_container)
        form.addRow(QLabel("Noise Pattern"), self.cb_noise)

        self.cb_metric = QComboBox(selection_container)
        form.addRow(QLabel("Counter"), self.cb_metric)

        form.addRow(QWidget(), QWidget())
        form.addRow(QLabel("Scores:"), QWidget())

        self.lb_score_deviation = QLabel(self)
        form.addRow(QLabel("Deviation:"), self.lb_score_deviation)

        self.lb_score_susceptibility = QLabel(self)
        form.addRow(QLabel("Suscept.:"), self.lb_score_susceptibility)

        self.lb_rating = QLabel(self)
        form.addRow(QLabel("Resilience:"), self.lb_rating)

        self.update_ui()

        plt_mgr.reconfigured.connect(self.update_all)

        self.cb_benchmark.currentIndexChanged.connect(self.update_config)
        self.cb_system.currentIndexChanged.connect(self.update_config)
        self.cb_noise.currentIndexChanged.connect(self.update_config)
        self.cb_metric.currentIndexChanged.connect(self.update_config)

        self.update_all()

    def set_score(self, score: scr.score):
        self.score = score
        self.update_ui()

    def set_measurement_info(self, info: util.measurement_info):
        self.plot_info = info
        self.update_ui()
        self.parent.update_score()
        self.selection_changed.emit()

    def update_ui(self):
        if self.score is None:
            self.lb_score_deviation.setText("-")
            self.lb_score_susceptibility.setText("-")
            self.lb_rating.setText("-")
        else:
            self.lb_score_deviation.setText(f"{max(self.score.dev_ref, self.score.dev_noisy):.4f}%")
            self.lb_score_susceptibility.setText(f"{self.score.susceptibility:.4f}")

            self.lb_rating.setText(f"{self.score.rel_resilience:.2f}")

            color = score_color(self.score.rel_resilience)
            hexcolor = QColor(color[0] * 255, color[1] * 255, color[2] * 255).name()
            self.lb_rating.setStyleSheet(f"QLabel {{ color : {hexcolor}; }}")

        if self.currently_updating_:
            return
        self.currently_updating_ = True

        update_choices(self.cb_benchmark, self.plt_mgr.benchmarks)
        update_choices(self.cb_system, self.plt_mgr.systems)
        update_choices(
            self.cb_noise,
            filter(lambda s: s != "NO_NOISE", self.plt_mgr.noise_patterns),
        )
        update_choices(self.cb_metric, self.plt_mgr.metrics)

        self.cb_benchmark.setCurrentText(self.plot_info.benchmark)
        self.cb_system.setCurrentText(self.plot_info.system)
        self.cb_noise.setCurrentText(self.plot_info.noise_pattern)
        self.cb_metric.setCurrentText(self.plot_info.counter)

        self.currently_updating_ = False

    def update_config(self):
        if self.currently_updating_:
            return
        self.currently_updating_ = True

        self.plot_info.benchmark = self.cb_benchmark.currentText()
        self.plot_info.system = self.cb_system.currentText()
        self.plot_info.noise_pattern = self.cb_noise.currentText()
        self.plot_info.counter = self.cb_metric.currentText()
        self.selection_changed.emit()

        self.currently_updating_ = False

    def update_all(self):
        self.update_ui()
        self.update_config()


class chart(QSplitter):
    def __init__(self, appstate):
        super().__init__()
        self.setOrientation(Qt.Horizontal)

        self.plt_mgr = appstate.plt_mgr

        self.fig = Figure(figsize=(10, 3), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.margins(x=0)
        self.canvas = FigureCanvasQTAgg(self.fig)

        self.controls = chart_controls(self, self.plt_mgr)
        self.controls.selection_changed.connect(self.update_plot)
        self.controls.update()

        self.setMinimumHeight(0)
        sp = self.controls.sizePolicy()
        sp.setHorizontalStretch(10)
        sp.setVerticalPolicy(QSizePolicy.MinimumExpanding)
        self.controls.setSizePolicy(sp)
        self.addWidget(self.controls)

        sp = self.canvas.sizePolicy()
        sp.setHorizontalStretch(90)
        self.canvas.setSizePolicy(sp)
        self.addWidget(self.canvas)

        self.plt_mgr.result_ready.connect(self.handle_result)
        self.plt_mgr.reconfigured.connect(self.update_plot)

    # Check if a new result fits this chart's info and plot it if applicable
    def handle_result(self, a: util.measurement_info):
        b = self.controls.plot_info
        self.update_score()
        if (
            a.benchmark == b.benchmark
            and a.system == b.system
            and a.counter == b.counter
            and (a.noise_pattern in ["NO_NOISE", b.noise_pattern])
        ):
            self.update_plot()

    # Try to create the plot from the available plot info
    def update_plot(self):
        self.update_score()
        self.fig.clear()
        self.ax.clear()
        self.fig.add_axes(self.ax)
        # This may just spawn an asynchronous calculation instead of plotting.
        # This function will be called again when the result is ready if that is the case.
        self.plt_mgr.get_plot(self.ax, self.controls.plot_info)
        self.fig.canvas.draw_idle()

    def update_score(self):
        self.controls.set_score(self.plt_mgr.request_score(self.controls.plot_info))
