# This file is part of the NORC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

from PySide6.QtWidgets import (
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QStyledItemDelegate,
    QStyle,
)
from PySide6.QtGui import QColor, QPainter, QPen, Qt
from PySide6.QtCore import Signal, QTimer

import matplotlib
import numpy as np

import norc.helpers.util as util
from norc.ui.ui_util import score_color
from norc.core.plotmanager import PlotManager
from norc.ui.qt_utils import table_dimensions, enable_two_line_header, wrappable_labels


class dashed_outline_delegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        # Check if this cell is selected
        is_selected = option.state & QStyle.State_Selected

        # Draw the cell without selection highlight
        if is_selected:
            option.state &= ~QStyle.State_Selected

        super().paint(painter, option, index)

        # Draw dashed border if selected
        if is_selected:
            pen = QPen()
            pen.setColor(QColor(0, 0, 0))
            pen.setStyle(Qt.PenStyle.DotLine)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))


class score_cell(QTableWidgetItem):
    def __init__(self, plt_mgr: PlotManager, info: util.measurement_info):
        super().__init__()

        self.plt_mgr = plt_mgr
        self.info = info

        self.setText("-")

        self.update_score()

    def set_bg(self, color: QColor):
        self.setBackground(color)
        # Black has sufficient contrast to al of the RdYlGn color scale.
        self.setForeground(QColor(0, 0, 0))

    def update_score(self):
        score = self.plt_mgr.request_score(self.info)
        if score is None or np.isinf(score.rel_resilience):
            self.setText("-")
            self.set_bg(QColor(255, 255, 255))
            return

        self.setText(f"{score.rel_resilience:.2f}")

        color = score_color(score.rel_resilience, self.plt_mgr.colormap)
        self.set_bg(QColor(color[0] * 255, color[1] * 255, color[2] * 255))


class score_table(QTableWidget):
    info_selected = Signal(util.measurement_info)

    def __init__(self, parent, plt_mgr: PlotManager):
        super().__init__(parent)
        self.plt_mgr = plt_mgr
        self.selected = None
        self.outer_dims = ["Benchmark", "System"]
        self.inner_dims = ["Counter", "Noise"]

        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.setInterval(200)  # Debounce updates to 5 times per second
        self.update_timer.timeout.connect(self.update_scores)

        self.plt_mgr.reconfigured.connect(self.update_table)
        self.plt_mgr.score_ready.connect(self.trigger_update)

        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        enable_two_line_header(self.horizontalHeader())
        enable_two_line_header(self.verticalHeader())

        self.update_table()

    def trigger_update(self, _):
        if not self.update_timer.isActive():
            self.update_timer.start()

    def update_scores(self):
        for ocol in range(self.columnCount()):
            for orow in range(self.rowCount()):
                table = self.cellWidget(orow, ocol)
                if isinstance(table, QTableWidget):
                    for icol in range(table.columnCount()):
                        for irow in range(table.rowCount()):
                            item = table.item(irow, icol)
                            if isinstance(item, score_cell):
                                item.update_score()

    def set_dimensions(self, orow: str, ocol: str, irow: str, icol: str):
        self.outer_dims = [ocol, orow]
        self.inner_dims = [icol, irow]
        self.update_table()

    def dim_items(self, dim_id: str):
        return sorted(
            {
                "Benchmark": self.plt_mgr.benchmarks,
                "System": self.plt_mgr.systems,
                "Counter": self.plt_mgr.metrics,
                "Noise": self.plt_mgr.noise_patterns.difference({"NO_NOISE"}),
            }[dim_id]
        )

    def get_cell_info(self, od0: str, od1: str, id0: str, id1: str):
        # Create a dictionary of dimension names and their values
        dimensions = {
            self.outer_dims[0]: od0,
            self.outer_dims[1]: od1,
            self.inner_dims[0]: id0,
            self.inner_dims[1]: id1,
        }

        # Construct a plot info from the dimension mapping
        info = util.measurement_info()
        info.benchmark = dimensions["Benchmark"]
        info.system = dimensions["System"]
        info.counter = dimensions["Counter"]
        info.noise_pattern = dimensions["Noise"]

        return info

    def update_table(self):
        self.clear()

        odim0 = self.dim_items(self.outer_dims[0])
        odim1 = self.dim_items(self.outer_dims[1])
        idim0 = self.dim_items(self.inner_dims[0])
        idim1 = self.dim_items(self.inner_dims[1])

        self.setColumnCount(len(odim0))
        self.setHorizontalHeaderLabels(wrappable_labels(odim0))
        self.setRowCount(len(odim1))
        self.setVerticalHeaderLabels(wrappable_labels(odim1))

        for ocol, od0 in enumerate(odim0):
            for orow, od1 in enumerate(odim1):
                table = QTableWidget()
                table.setColumnCount(len(idim0))
                table.setHorizontalHeaderLabels(wrappable_labels(idim0))
                table.setRowCount(len(idim1))
                table.setVerticalHeaderLabels(wrappable_labels(idim1))

                # Apply custom delegate for dashed outline selection
                delegate = dashed_outline_delegate()
                table.setItemDelegate(delegate)

                table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
                table.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
                enable_two_line_header(table.horizontalHeader())
                enable_two_line_header(table.verticalHeader())

                for icol, id0 in enumerate(idim0):
                    for irow, id1 in enumerate(idim1):
                        table.setItem(
                            irow,
                            icol,
                            score_cell(
                                self.plt_mgr,
                                self.get_cell_info(od0, od1, id0, id1),
                            ),
                        )

                table.itemClicked.connect(self.handleCellActivated)
                w, h = table_dimensions(table, 10, 5)
                self.setColumnWidth(ocol, w)
                self.setRowHeight(orow, h)

                self.setCellWidget(orow, ocol, table)

    def handleCellActivated(self, cell):
        self.info_selected.emit(cell.info)
