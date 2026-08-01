# This file is part of the NORC software
#
# Copyright (c) 2026, Technical University of Darmstadt, Germany
#
# This software may be modified and distributed under the terms of a BSD-style license.
# See the LICENSE file in the base directory for details.

import contextlib
import io
import os

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QCheckBox,
    QPlainTextEdit,
    QFileDialog,
    QDialogButtonBox,
)

from norc.core.generate import main as generate_main, extract_variables


class generate_dialog(QDialog):
    """Dialog wrapping norc_generate: builds a measurement orchestration
    script for the currently open experiment from a template script."""

    def __init__(self, appstate, parent=None):
        super().__init__(parent)
        self.appstate = appstate

        self.setWindowTitle("Create Measurement Runner")
        self.resize(560, 640)

        selection = appstate.plt_mgr.plot_settings.selection

        layout = QVBoxLayout(self)

        form = QFormLayout()
        layout.addLayout(form)

        form.addRow(QLabel(f"Experiment: {appstate.plt_mgr.experiment_root or '(none open)'}"))

        self.le_template = QLineEdit()
        self.le_template.textChanged.connect(self.update_detected_variables)
        btn_template = QPushButton("Browse...")
        btn_template.clicked.connect(self.browse_template)
        template_row = QHBoxLayout()
        template_row.addWidget(self.le_template)
        template_row.addWidget(btn_template)
        form.addRow("Template script:", template_row)

        self.sb_top = QSpinBox()
        self.sb_top.setRange(1, 999)
        self.sb_top.setValue(10)
        form.addRow("Top N counters (cap):", self.sb_top)

        self.cb_auto_cutoff = QCheckBox("Auto-select via cutoff detection")
        self.cb_auto_cutoff.setToolTip(
            "Select counters up to the cutoff of the sorted resilience "
            "curve instead of a fixed count. Still capped by 'Top N' and "
            "filtered by 'Min resilience'."
        )
        form.addRow(self.cb_auto_cutoff)

        self.sb_min_resilience = QDoubleSpinBox()
        self.sb_min_resilience.setRange(0.0, 1.0)
        self.sb_min_resilience.setSingleStep(0.05)
        self.sb_min_resilience.setValue(0.9)
        form.addRow("Min resilience:", self.sb_min_resilience)

        self.sb_contribution = QDoubleSpinBox()
        self.sb_contribution.setRange(0.0, 100.0)
        self.sb_contribution.setValue(selection.contrib_threshold)
        form.addRow("Min contribution %:", self.sb_contribution)

        self.sb_visits = QSpinBox()
        self.sb_visits.setRange(0, 1_000_000)
        self.sb_visits.setValue(selection.visit_threshold)
        form.addRow("Min visits:", self.sb_visits)

        self.var_group = QGroupBox("Detected variables (@@var@@)")
        self.var_form = QFormLayout()
        self.var_group.setLayout(self.var_form)
        self.var_inputs = {}
        form.addRow(self.var_group)

        self.cb_script_type = QComboBox()
        self.cb_script_type.addItems(["Auto-detect", "Force sbatch", "Force shell"])
        form.addRow("Script type:", self.cb_script_type)

        self.sb_iterations = QSpinBox()
        self.sb_iterations.setRange(1, 100000)
        self.sb_iterations.setValue(1)
        form.addRow("Iterations:", self.sb_iterations)

        self.le_prefix = QLineEdit()
        self.le_prefix.setPlaceholderText("Optional Extra-P prefix")
        form.addRow("Prefix:", self.le_prefix)

        self.cb_capture_logs = QCheckBox("Redirect job/template output into logs/")
        self.cb_capture_logs.setChecked(True)
        form.addRow(self.cb_capture_logs)

        self.le_output = QLineEdit("measure.sh")
        btn_output = QPushButton("Browse...")
        btn_output.clicked.connect(self.browse_output)
        output_row = QHBoxLayout()
        output_row.addWidget(self.le_output)
        output_row.addWidget(btn_output)
        form.addRow("Output script:", output_row)

        self.pte_result = QPlainTextEdit()
        self.pte_result.setReadOnly(True)
        self.pte_result.setPlaceholderText("Output of norc_generate will appear here.")
        layout.addWidget(self.pte_result)

        buttons = QDialogButtonBox()
        self.btn_generate = buttons.addButton("Generate", QDialogButtonBox.ActionRole)
        self.btn_generate.clicked.connect(self.run_generate)
        buttons.addButton(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.update_detected_variables()

    def browse_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select template script")
        if path:
            self.le_template.setText(path)

    def browse_output(self):
        path, _ = QFileDialog.getSaveFileName(self, "Select output script", self.le_output.text())
        if path:
            self.le_output.setText(path)

    def update_detected_variables(self):
        """Re-scan the selected template for @@var@@ placeholders and
        rebuild one value-range input per detected variable."""
        while self.var_form.rowCount():
            self.var_form.removeRow(0)
        self.var_inputs = {}

        path = self.le_template.text().strip()
        variables = set()
        if path and os.path.isfile(path):
            try:
                with open(path, 'r') as f:
                    variables = extract_variables(f.read())
            except OSError:
                variables = set()

        if not variables:
            self.var_form.addRow(QLabel("No @@var@@ placeholders detected."))
            return

        for name in sorted(variables):
            le = QLineEdit()
            le.setPlaceholderText("comma-separated values, e.g. 1,2,4")
            self.var_inputs[name] = le
            self.var_form.addRow(f"{name}:", le)

    def build_argv(self):
        experiment_root = self.appstate.plt_mgr.experiment_root
        template_script = self.le_template.text().strip()

        argv = [experiment_root, template_script]

        argv += ["--top", str(self.sb_top.value())]
        if self.cb_auto_cutoff.isChecked():
            argv.append("--auto-cutoff")
        argv += ["--min-resilience", str(self.sb_min_resilience.value())]
        argv += ["--contribution", str(self.sb_contribution.value())]
        argv += ["--visits", str(self.sb_visits.value())]

        for name, le in self.var_inputs.items():
            values = le.text().strip()
            if values:
                argv += ["--var", f"{name}={values}"]

        script_type = self.cb_script_type.currentText()
        if script_type == "Force sbatch":
            argv.append("--sbatch")
        elif script_type == "Force shell":
            argv.append("--no-sbatch")

        argv += ["--iterations", str(self.sb_iterations.value())]

        prefix = self.le_prefix.text().strip()
        if prefix:
            argv += ["--prefix", prefix]

        if not self.cb_capture_logs.isChecked():
            argv.append("--no-log-capture")

        output = self.le_output.text().strip() or "measure.sh"
        argv += ["--output", output]

        return argv

    def run_generate(self):
        experiment_root = self.appstate.plt_mgr.experiment_root
        template_script = self.le_template.text().strip()

        if not experiment_root:
            self.show_result("Error: no experiment is currently open.", success=False)
            return
        if not template_script or not os.path.isfile(template_script):
            self.show_result("Error: please select an existing template script.", success=False)
            return

        argv = self.build_argv()

        out_buf, err_buf = io.StringIO(), io.StringIO()
        exit_code = 0
        try:
            with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
                generate_main(argv)
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else 1
        except Exception as e:
            err_buf.write(f"Unexpected error: {e}\n")
            exit_code = 1

        output_text = out_buf.getvalue() + err_buf.getvalue()
        self.show_result(output_text, success=(exit_code == 0))

    def show_result(self, text, success):
        self.pte_result.setPlainText(text)
        self.pte_result.setStyleSheet(
            "" if success else "QPlainTextEdit { background-color: #fdd; }"
        )