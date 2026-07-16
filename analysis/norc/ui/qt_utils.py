# This file is part of the NORC software
#
# Copyright (c) 2024-2025, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

from PySide6.QtWidgets import QComboBox, QTableWidget, QHeaderView
from PySide6.QtCore import Qt


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
    """Compute the size needed to display a table without truncating its
    contents. Uses content-based size hints rather than the headers'
    current sectionSize, since sectionSize reflects whatever the Stretch
    resize mode has assigned so far (which may be smaller than the
    content needs, e.g. before the table has been laid out) rather than
    the space actually required."""
    hhead = table.horizontalHeader()
    vhead = table.verticalHeader()
    # Use whichever of width()/sizeHint() is larger: a header that hasn't
    # been shown/laid out yet can report a stale/zero width() even after
    # its minimum size has been set.
    w = max(vhead.width(), vhead.sizeHint().width())
    h = max(hhead.height(), hhead.sizeHint().height())
    for i in range(table.columnCount()):
        w += max(
            table.sizeHintForColumn(i),
            hhead.sectionSizeHint(i),
            hhead.minimumSectionSize(),
            min_it_w,
        )

    for i in range(table.rowCount()):
        h += max(
            table.sizeHintForRow(i),
            vhead.sectionSizeHint(i),
            vhead.minimumSectionSize(),
            min_it_h,
        )

    # Account for the table's own frame border, otherwise content flush
    # against it can trigger scrollbars that eat into the space computed
    # above and truncate the last row/column.
    w += 2 * table.frameWidth()
    h += 2 * table.frameWidth()

    return w, h


def enable_two_line_header(header: QHeaderView, lines: int = 2):
    """Give a table header enough room to display labels that span
    multiple lines (see wrappable_labels).

    For a horizontal header, all columns share the same header height, so
    setMinimumHeight on the header widget is what's needed. A vertical
    header's "height" is the sum of all of its row sections though, so the
    same call there would only guarantee that much room in total, not per
    row - each row needs its own minimum size instead."""
    fm = header.fontMetrics()
    min_size = fm.height() * lines + 10
    if header.orientation() == Qt.Orientation.Horizontal:
        header.setMinimumHeight(min_size)
    else:
        header.setMinimumSectionSize(min_size)


def prevent_stretch_truncation(table: QTableWidget, min_it_w=0, min_it_h=0):
    """When a header's resize mode is Stretch, sections are stretched to
    evenly fill the available space regardless of each section's own
    content size. If some columns/rows need more room than others, that
    even split can shrink them below what their content needs, truncating
    values. Set a uniform minimum section size - the widest content found
    in any column/row - so Stretch can still grow sections to fill extra
    space, but never shrinks one below what its content needs.

    Call this after the table's items have been populated, since it relies
    on their content size hints."""
    hhead = table.horizontalHeader()
    vhead = table.verticalHeader()
    if table.columnCount():
        col_w = max(
            [table.sizeHintForColumn(i) for i in range(table.columnCount())]
            + [min_it_w, hhead.minimumSectionSize()]
        )
        hhead.setMinimumSectionSize(col_w)

    if table.rowCount():
        row_h = max(
            [table.sizeHintForRow(i) for i in range(table.rowCount())]
            + [min_it_h, vhead.minimumSectionSize()]
        )
        vhead.setMinimumSectionSize(row_h)


def wrappable_labels(labels):
    """Break long, underscore-separated names (e.g. counter names) onto a
    second line by replacing the underscore closest to the middle of the
    label with a newline. QHeaderView renders embedded newlines natively,
    it just doesn't support automatic word wrapping."""
    wrapped = []
    for label in labels:
        positions = [i for i, c in enumerate(label) if c == "_"]
        if not positions:
            wrapped.append(label)
            continue
        mid = len(label) / 2
        split = min(positions, key=lambda i: abs(i - mid))
        wrapped.append(label[:split] + "\n" + label[split + 1:])
    return wrapped
