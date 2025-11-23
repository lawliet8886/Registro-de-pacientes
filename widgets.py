from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QLabel, QLineEdit


class ClickLabel(QLabel):
    clicked = pyqtSignal()

    def mouseReleaseEvent(self, ev):
        self.clicked.emit()


class MyLineEdit(QLineEdit):
    def keyPressEvent(self, e):
        super().keyPressEvent(e)
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.focusNextChild()
