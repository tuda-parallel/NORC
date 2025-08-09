# This file is part of the NORC software
#
# Copyright (c) 2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import matplotlib
from PySide6.QtWidgets import QWidget, QSizePolicy


def score_color(score):
    return matplotlib.colormaps["turbo"](0.5 + (1.0 - score) * 0.5)


def add_v_spacer(target):
    spacer = QWidget(target)
    spacer.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
    target.layout().addWidget(spacer)


def clear_widget(w):
    if w is None or w.layout() is None:
        return
    layout = w.layout()
    for i in range(layout.count()):
        if layout.itemAt(i) is None:
            continue
        layout.itemAt(i).widget().setParent(None)
