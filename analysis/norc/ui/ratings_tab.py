# This file is part of the NORHC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

from PySide6.QtWidgets import QWidget, QVBoxLayout, QSplitter
from PySide6.QtGui import Qt

from norhc.ui.score_table import score_table
from norhc.ui.dimension_picker import dimension_picker
from norhc.ui.chart import chart


class ratings_tab(QWidget):
    def __init__(self, appstate):
        super().__init__()
        self.appstate = appstate
        self.setLayout(QVBoxLayout())
        # self.ui = appstate.load_ui("ratings_tab.ui")

        vsplit = QSplitter(orientation=Qt.Vertical)
        table_hsplit = QSplitter(orientation=Qt.Horizontal)
        self.layout().addWidget(vsplit)

        # self.layout().addWidget(self.ui)

        table = score_table(self, appstate.plt_mgr)
        dimpik = dimension_picker(appstate, "system", "benchmark", "noise", "metric")
        chrt = chart(appstate)

        table.info_selected.connect(chrt.controls.set_measurement_info)
        dimpik.dimensions_changed.connect(table.set_dimensions)

        table_hsplit.addWidget(table)
        table_hsplit.addWidget(dimpik)
        vsplit.addWidget(table_hsplit)
        vsplit.addWidget(chrt)
