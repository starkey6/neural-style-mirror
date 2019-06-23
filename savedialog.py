# -*- coding: utf-8 -*-
from __future__ import print_function, division, absolute_import

import os

from qtpy.QtCore import QDir
from qtpy.QtWidgets import QFileDialog


def handle_capture(window, capture):
    file_format = 'png'
    initial_path = os.path.join(QDir.currentPath(), capture.style_name + '.' + str(file_format))
    filter = '%s Files (*.%s);;All Files (*)' % (str(file_format).upper(), file_format)
    file_name, _ = QFileDialog.getSaveFileName(window, 'Save As', initial_path, filter)
    if file_name:
        capture.image.save(file_name, str(file_format))
