# This file is part of the NORHC software
#
# Copyright (c) 2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import os
from norhc.core.plotmanager import PlotManager


class ApplicationState:
    def __init__(self, loader):
        script_location = os.path.dirname(os.path.abspath(__file__))
        self.ui_dir = os.path.join(script_location, "..", "ui")
        self.ui_dir = os.path.abspath(self.ui_dir)

        self.loader = loader
        self.plt_mgr = PlotManager()

    def load_ui(self, fname):
        """Load a .ui file from the UI directory."""
        return self.loader.load(os.path.join(self.ui_dir, fname), None)
