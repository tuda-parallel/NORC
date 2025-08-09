# This file is part of the NORHC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import Signal

from norhc.ui.qt_utils import update_choices


class dimension_picker(QWidget):
    dimensions_changed = Signal(str, str, str, str)

    def __init__(self, appstate, orow, ocol, irow, icol):
        super().__init__()
        self.ui = appstate.load_ui("dimension_picker.ui")
        self.dimensions = {orow, ocol, irow, icol}
        self.currently_updating_ = False

        self.setLayout(QVBoxLayout())
        self.layout().addWidget(self.ui)

        self.update_avail_dimensions()
        self.ui.cb_row_outer.setCurrentText(orow)
        self.ui.cb_col_outer.setCurrentText(ocol)
        self.ui.cb_row_inner.setCurrentText(irow)
        self.ui.cb_col_inner.setCurrentText(icol)

        self.ui.cb_row_outer.currentTextChanged.connect(lambda: self.selection_changed("row_outer"))
        self.ui.cb_col_outer.currentTextChanged.connect(lambda: self.selection_changed("col_outer"))
        self.ui.cb_row_inner.currentTextChanged.connect(lambda: self.selection_changed("row_inner"))
        self.ui.cb_col_inner.currentTextChanged.connect(lambda: self.selection_changed("col_inner"))

    def update_avail_dimensions(self):
        if self.currently_updating_:
            return
        self.currently_updating_ = True
        update_choices(self.ui.cb_row_outer, self.dimensions)
        update_choices(self.ui.cb_col_outer, self.dimensions)
        update_choices(self.ui.cb_row_inner, self.dimensions)
        update_choices(self.ui.cb_col_inner, self.dimensions)
        self.currently_updating_ = False

    def selection_changed(self, master: str):
        if self.currently_updating_:
            return
        self.currently_updating_ = True

        # This list defines the comboboxes' update order. Boxes that would have dimensions already taken by earlier ones will be cleared.
        cbs = [
            self.ui.cb_row_outer.currentText(),
            self.ui.cb_col_outer.currentText(),
            self.ui.cb_row_inner.currentText(),
            self.ui.cb_col_inner.currentText(),
        ]

        # Translate master name to cbs list index.
        master_idx = {
            "row_outer": 0,
            "col_outer": 1,
            "row_inner": 2,
            "col_inner": 3,
        }.get(master, 0)

        # Put the master box first in the list so it will not be prevented from changing by anything else.
        cbs[0], cbs[master_idx] = cbs[master_idx], cbs[0]

        # Clear all boxes with already-taken dimensions.
        taken_dimensions = set()
        for idx, cb in enumerate(cbs):
            if cb in taken_dimensions:
                cbs[idx] = ""
                continue
            if cb:
                taken_dimensions.add(cb)

        # Fill in remaining available dimensions where nothing is specified
        avail_dimensions = self.dimensions - taken_dimensions
        for idx, cb in enumerate(cbs):
            if not avail_dimensions:
                break
            if not cb:
                cbs[idx] = avail_dimensions.pop()

        # Swap box contents back for writing.
        cbs[0], cbs[master_idx] = cbs[master_idx], cbs[0]

        self.ui.cb_row_outer.setCurrentText(cbs[0])
        self.ui.cb_col_outer.setCurrentText(cbs[1])
        self.ui.cb_row_inner.setCurrentText(cbs[2])
        self.ui.cb_col_inner.setCurrentText(cbs[3])

        # Publish changed dimensions
        self.dimensions_changed.emit(
            self.ui.cb_row_outer.currentText(),
            self.ui.cb_col_outer.currentText(),
            self.ui.cb_row_inner.currentText(),
            self.ui.cb_col_inner.currentText(),
        )

        self.currently_updating_ = False
