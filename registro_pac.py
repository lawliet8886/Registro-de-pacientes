from main import Main
from PyQt5.QtWidgets import QApplication
import sys


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Main()
    w.show()
    sys.exit(app.exec_())
