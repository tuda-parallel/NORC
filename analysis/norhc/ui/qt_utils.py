# This file is part of the NORHC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

from PySide6.QtWidgets import QComboBox, QTableWidget


def update_choices(cb: QComboBox, choices):
    block = cb.blockSignals(True)
    prev_choice = cb.currentText()

    cb.clear()
    cb.addItems(sorted(list(choices)))

    idx = cb.findText(prev_choice)
    if idx >= 0:
        cb.setCurrentIndex(idx)

    cb.blockSignals(block)


def table_dimensions(table: QTableWidget, min_it_w=0, min_it_h=0):
    hhead = table.horizontalHeader()
    vhead = table.verticalHeader()
    w = vhead.width()
    h = hhead.height()
    for i in range(hhead.count()):
        w += max(hhead.sectionSize(i), min_it_w)

    for i in range(vhead.count()):
        h += max(vhead.sectionSize(i), min_it_h)

    return w, h
