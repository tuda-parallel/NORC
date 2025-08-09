# This file is part of the NORC software
#
# Copyright (c) 2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QColor
from norc.classes.application_state import ApplicationState
from norc.ui.mainwindow import main_window


def main() -> None:
    loader = QUiLoader()
    app = QApplication(sys.argv)
    # app.setStyle("Windows")
    app.setPalette(QColor(255, 255, 255, 255))
    appstate = ApplicationState(loader)

    if len(sys.argv) > 1:
        appstate.plt_mgr.open_experiment(sys.argv[1])

    mw = main_window(appstate)

    app.exec()


if __name__ == "__main__":
    main()

