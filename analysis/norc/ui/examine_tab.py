# This file is part of the NORHC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

from PySide6.QtWidgets import QWidget, QSplitter, QVBoxLayout
from PySide6.QtGui import Qt

from norhc.ui.chart import chart


class examine_tab(QWidget):
    def __init__(self, appstate):
        super().__init__()
        self.setContentsMargins(0, 0, 0, 0)
        self.appstate = appstate
        self.ui = appstate.load_ui("examine_tab.ui")
        self.setLayout(QVBoxLayout())
        self.layout().addWidget(self.ui)

        self.chart_splitter = QSplitter(orientation=Qt.Vertical)
        self.ui.sa_charts.setWidget(self.chart_splitter)

        self.ui.pb_addchart.clicked.connect(self.add_chart)

    def add_chart(self):
        self.chart_splitter.addWidget(chart(self.appstate))
