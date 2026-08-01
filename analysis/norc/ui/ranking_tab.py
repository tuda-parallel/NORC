# This file is part of the NORC software
#
# Copyright (c) 2026, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import matplotlib

matplotlib.use("QtAgg")

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT as FigNavigation,
)

from PySide6.QtWidgets import QWidget, QVBoxLayout, QProgressDialog, QApplication
from PySide6.QtCore import Qt

from norc.core.score import compute_scores, plot_resilience_curve, ScoreComputationCancelled
from norc.helpers.util import data_selection


class ranking_tab(QWidget):
    """The Ranking tab: shows counters ranked by relative resilience (best to worst), with the
    knee/elbow point marked -- the same point `--auto-knee` in norc_generate
    would cut the selection at."""

    def __init__(self, appstate):
        super().__init__()
        self.plt_mgr = appstate.plt_mgr

        self.fig = Figure(figsize=(6, 4), dpi=100, layout="constrained")
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasQTAgg(self.fig)

        self.setLayout(QVBoxLayout(self))
        self.layout().addWidget(FigNavigation(self.canvas, self))
        self.layout().addWidget(self.canvas)

        self._cache_key = None
        self._sorted_counters = None

        self.plt_mgr.reconfigured.connect(self.update_plot)
        self.update_plot()

    def update_plot(self):
        self.ax.clear()

        if not self.plt_mgr.experiment_root:
            self._cache_key = None
            self._sorted_counters = None
            self.ax.set_title("No experiment open")
            self.canvas.draw_idle()
            return

        # The ranking only depends on the experiment and the two thresholds
        # below, not on the rest of plt_mgr's (interactive) settings, so skip
        # the expensive recompute when neither has actually changed.
        cache_key = (
            self.plt_mgr.experiment_root,
            self.plt_mgr.plot_settings.selection.contrib_threshold,
            self.plt_mgr.plot_settings.selection.visit_threshold,
        )
        if cache_key != self._cache_key:
            # Ranking is expensive; skip it while the tab isn't shown. update_plot()
            # runs again from showEvent() once it becomes visible, with _cache_key
            # left stale so the check above re-triggers the recompute.
            if not self.isVisible():
                return

            selection = data_selection()
            selection.lump_benchmarks = True
            selection.lump_systems = True
            selection.lump_noise = True
            selection.lump_params = True
            selection.lump_resources = True
            selection.contrib_threshold = cache_key[1]
            selection.visit_threshold = cache_key[2]

            progress = QProgressDialog("Calculating scores…", "Cancel", 0, 0, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setAutoClose(False)
            progress.setAutoReset(False)

            def on_progress(done, total):
                progress.setMaximum(total)
                progress.setValue(done)
                QApplication.processEvents()
                if progress.wasCanceled():
                    raise ScoreComputationCancelled()

            try:
                sgp = compute_scores(self.plt_mgr.experiment_root, selection, progress_callback=on_progress)
            except ScoreComputationCancelled:
                self._cache_key = None
                self._sorted_counters = None
                self.ax.set_title("Score calculation cancelled")
                self.canvas.draw_idle()
                return
            except Exception as e:
                self._cache_key = None
                self._sorted_counters = None
                self.ax.set_title(f"Error computing scores: {e}")
                self.canvas.draw_idle()
                return
            finally:
                progress.close()

            self._sorted_counters = sorted(sgp.scores.items(), key=lambda it: it[1].rel_resilience, reverse=True)
            self._cache_key = cache_key

        plot_resilience_curve(self.ax, self._sorted_counters)
        self.canvas.draw_idle()

    def showEvent(self, event):
        super().showEvent(event)
        self.update_plot()
