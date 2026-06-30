# This file is part of the NORC software
#
# Copyright (c) 2025-2026, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import sys
from PySide6.QtWidgets import QApplication, QToolTip
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QColor, QPalette, Qt
from norc.classes.application_state import ApplicationState
from norc.ui.mainwindow import main_window


def main() -> None:
    loader = QUiLoader()
    app = QApplication(sys.argv)
    apply_style(app)
    appstate = ApplicationState(loader)

    if len(sys.argv) > 1:
        appstate.plt_mgr.open_experiment(sys.argv[1])

    mw = main_window(appstate)

    app.exec()


def apply_style(app):
    app.setStyle('Fusion')

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(210, 210, 210))
    palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.black)
    palette.setColor(QPalette.ColorRole.Base, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(10, 10, 10))
    palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.black)
    palette.setColor(QPalette.ColorRole.Button, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.black)
    palette.setColor(QPalette.ColorRole.Highlight, QColor(31, 119, 180))
    palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(230, 230, 230))
    palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.black)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(80, 80, 80))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(80, 80, 80))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor(150, 150, 150))
    palette.setColor(QPalette.ColorRole.Link, QColor(21, 83, 123))
    app.setPalette(palette)
    QToolTip.setPalette(palette)


if __name__ == "__main__":
    main()
