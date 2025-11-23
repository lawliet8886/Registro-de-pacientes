import sqlite3

from PyQt5.QtCore import QDate, QTime
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QTimeEdit,
)

from backup import DB_PATH


class SimpleTimeDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QFormLayout(self)
        self.t = QTimeEdit(displayFormat="HH:mm")
        self.t.setTime(QTime.currentTime())
        lay.addRow("Hora aproximada:", self.t)
        lay.addRow("", QPushButton("Salvar ✅", clicked=self.accept))

    def hour(self) -> str:
        return self.t.time().toString("HH:mm")


class TimeIntervalDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Intervalo de Convivência 🕒")
        lay = QFormLayout(self)
        self.start = QTimeEdit(displayFormat="HH:mm")
        self.end = QTimeEdit(displayFormat="HH:mm")
        lay.addRow("Início:", self.start)
        lay.addRow("Fim:", self.end)
        lay.addRow("", QPushButton("Salvar ✅", clicked=self.accept))

    def interval(self):
        return (
            self.start.time().toString("HH:mm"),
            self.end.time().toString("HH:mm"),
        )


class EncaminhamentoDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tipo de Encaminhamento 🤝")
        lay = QFormLayout(self)
        self.cmb = QComboBox()
        self.cmb.addItems([
            "Demanda Espontânea",
            "Abordagem na Rua",
            "Abrigo",
            "Ambulatório",
            "Atenção Básica",
            "Caps da RAPS Municipal",
            "Caps de outro Município",
            "Comunidade Terapêutica",
            "Conselho Tutelar",
            "Consultório na Rua",
            "CREAS/CRAS",
            "Escola",
            "Emergência Clínica",
            " Emergência Psiquiátrica",
            "Hospital Geral",
            "Hospital Psiquiátrico",
            "Justiça",
            "Hospital Maternidade",
            "Rede Intersetorial",
            "Rede Privada Amb/Hospital",
        ])
        lay.addRow("Tipo:", self.cmb)
        lay.addRow("", QPushButton("Salvar ✅", clicked=self.accept))

    def choice(self):
        return self.cmb.currentText()


class SearchDialog(QDialog):
    """Diálogo de pesquisa avançada com listas dinâmicas de Demanda e Encaminhamento."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Buscar registros 🔍")
        lay = QFormLayout(self)

        self.txt_name = QLineEdit()
        self.txt_prof = QLineEdit()
        lay.addRow("Nome do paciente contém:", self.txt_name)
        lay.addRow("Profissional contém:", self.txt_prof)

        self.cmb_dmd = QComboBox()
        self.cmb_enc = QComboBox()

        self.d_ini = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.d_end = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.d_ini.setDate(QDate.currentDate().addMonths(-1))
        self.d_end.setDate(QDate.currentDate())

        self.d_ini.dateChanged.connect(lambda _: self._populate_combos())
        self.d_end.dateChanged.connect(lambda _: self._populate_combos())

        lay.addRow("Tipo de atendimento:", self.cmb_dmd)
        lay.addRow("Tipo de encaminhamento:", self.cmb_enc)
        lay.addRow("De:", self.d_ini)
        lay.addRow("Até:", self.d_end)

        self.chk_b = QCheckBox("Fez Desjejum 🥞")
        self.chk_l = QCheckBox("Fez Almoço 🥗")
        self.chk_s = QCheckBox("Fez Lanche 🥪")
        self.chk_d = QCheckBox("Fez Janta 🍛")
        for w in (self.chk_b, self.chk_l, self.chk_s, self.chk_d):
            lay.addRow(w)

        self.chk_adv = QCheckBox("Busca avançada (tokenizar nome/prof.)")
        lay.addRow(self.chk_adv)

        lay.addRow("", QPushButton("Buscar ✅", clicked=self.accept))

        self._populate_combos()

    def _date_iso_range(self):
        to_iso = lambda qdate: qdate.toString("yyyyMMdd")
        return to_iso(self.d_ini.date()), to_iso(self.d_end.date())

    def _populate_combos(self):
        d0, d1 = self._date_iso_range()

        self.cmb_dmd.blockSignals(True)
        self.cmb_dmd.clear()
        self.cmb_dmd.addItem("— Qualquer —", "")

        seen = set()
        with sqlite3.connect(DB_PATH) as c:
            for (demands,) in c.execute(
                """
                 SELECT DISTINCT demands FROM records
                  WHERE (substr(date,7,4)||substr(date,4,2)||substr(date,1,2))
                        BETWEEN ? AND ? AND demands IS NOT NULL
            """,
                (d0, d1),
            ):
                for tok in demands.split(","):
                    tok = tok.strip()
                    if not tok:
                        continue
                    code = tok.split(" ")[0]
                    seen.add(code)

        for code in sorted(seen):
            self.cmb_dmd.addItem(code, code)
        self.cmb_dmd.blockSignals(False)

        self.cmb_enc.blockSignals(True)
        self.cmb_enc.clear()
        self.cmb_enc.addItem("— Qualquer —", "")
        with sqlite3.connect(DB_PATH) as c:
            encs = [
                e
                for (e,) in c.execute(
                    """
                    SELECT DISTINCT encaminhamento FROM records
                     WHERE encaminhamento IS NOT NULL
                       AND (substr(date,7,4)||substr(date,4,2)||substr(date,1,2))
                           BETWEEN ? AND ?
            """,
                    (d0, d1),
                )
            ]
        for enc in sorted(encs):
            self.cmb_enc.addItem(enc, enc)
        self.cmb_enc.blockSignals(False)

    def filters(self):
        return dict(
            name=self.txt_name.text().strip(),
            prof=self.txt_prof.text().strip(),
            dmd=self.cmb_dmd.currentData(),
            enc=self.cmb_enc.currentData(),
            d_ini=self.d_ini.date().toString("dd/MM/yyyy"),
            d_end=self.d_end.date().toString("dd/MM/yyyy"),
            b=self.chk_b.isChecked(),
            l=self.chk_l.isChecked(),
            s=self.chk_s.isChecked(),
            d=self.chk_d.isChecked(),
            adv=self.chk_adv.isChecked(),
        )
