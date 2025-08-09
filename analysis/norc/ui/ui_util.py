# This file is part of the NORHC software
#
# Copyright (c) 2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import matplotlib


def score_color(score):
    return matplotlib.colormaps["turbo"](0.5 + (1.0 - score) * 0.5)
