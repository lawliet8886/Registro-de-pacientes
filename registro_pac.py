"""
Registro de Pacientes – v3.5 😎
==============================
• Aba Desjejum 🥞 e dashboard atualizado  
• Convívio (C) preenche e limpa refeições automaticamente  
• Log de alterações de refeições, com ✏️ ao lado do nome  
• Duplo-clique exibe histórico de refeições do paciente  
• Reativar 🔄 remove duplicado da aba “Saíram”  
• Compatível com bancos antigos (migração automática)

Requisito único: PyQt5
"""
import sys
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore  import Qt, QTime, QDate, QTimer
from PyQt5.QtGui   import QPixmap, QGuiApplication
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QLineEdit, QPushButton, QMessageBox,
    QVBoxLayout, QWidget, QHBoxLayout, QCheckBox, QDialog, QFormLayout,
    QTimeEdit, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QDateEdit, QTabWidget, QFileDialog, QProgressDialog, QInputDialog,
)

from infra import (
    CONFIG_FILE,
    _load_cfg,
    _save_cfg,
    backup_now,
    get_conn,
    init_db,
    _fix_old_imports,
)
from ui.dialogs import (
    EncaminhamentoDialog,
    SearchDialog,
    SimpleTimeDialog,
    TimeIntervalDialog,
)
from ui.widgets import MyLineEdit

# ─────────────────────────────────────── Constantes de horário
HORARIOS = {
    "desjejum": QTime.fromString("09:00", "HH:mm"),
    "almoco":   QTime.fromString("12:00", "HH:mm"),
    "lanche":   QTime.fromString("15:00", "HH:mm"),
    "janta":    QTime.fromString("18:00", "HH:mm"),
}

# Todos os códigos de demanda conhecidos
DEMAND_LIST = [
    "A", "R", "M", "AN", "AN Entrou", "AN Saiu", "C",
    "RM", "Grupos/Eventos", "Outros",
    "AI", "REA",
]


# ───────────────────────────────────────────────────────────── DB helpers

EXPECTED_COLS = [
    "patient_name", "demands", "reference_prof", "date",
    "enter_sys", "enter_inf", "left_sys", "left_inf",
    "observations", "encaminhamento",
    "desjejum", "lunch", "snack", "dinner",
    "start_time", "end_time", "archived_ai",
]


def add_record(row: dict):
    missing = [c for c in EXPECTED_COLS if c not in row]
    extra = [c for c in row if c not in EXPECTED_COLS]
    if missing or extra:
        raise ValueError(
            "Campos inválidos:" +
            (f" faltando {', '.join(missing)}" if missing else "") +
            (f"; extras {', '.join(extra)}" if extra else "")
        )

    cols = ", ".join(EXPECTED_COLS)
    qs = ", ".join("?" * len(EXPECTED_COLS))
    values = tuple(row[c] for c in EXPECTED_COLS)
    with get_conn() as c:
        c.execute(f"INSERT INTO records ({cols}) VALUES ({qs})", values)
        c.commit()

def update_meals(pid, new_b, new_l, new_s, new_d):
    with get_conn() as c:
        row = c.execute(
            "SELECT desjejum,lunch,snack,dinner FROM records WHERE id=?",
            (pid,)
        ).fetchone()

        if row is None:
            raise RuntimeError("ID não encontrado.")

        old_b, old_l, old_s, old_d = row

        if (old_b, old_l, old_s, old_d) == (new_b, new_l, new_s, new_d):
            return  # nada mudou

        c.execute("""
            UPDATE records SET desjejum=?, lunch=?, snack=?, dinner=?
            WHERE id=?
        """, (new_b, new_l, new_s, new_d, pid))

        # ⚠️ AGORA são 10 placeholders (record_id + 9 valores) 👇
        c.execute("""
            INSERT INTO meal_log (
                record_id, ts,
                old_b, old_l, old_s, old_d,
                new_b, new_l, new_s, new_d
            )
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            pid,
            datetime.now().strftime("%d/%m %H:%M"),
            old_b, old_l, old_s, old_d,
            new_b, new_l, new_s, new_d
        ))
        c.commit()

def _covers_interval(qt, start_t, end_t):
    if not (start_t and end_t):
        return False
    t0 = QTime.fromString(start_t, "HH:mm")
    t1 = QTime.fromString(end_t, "HH:mm")
    return t0 <= qt <= t1

def update_demands(pid, new_demands, new_start=None, new_end=None, new_enc=None):
    """
    • Se o registro tinha AI/REA e o usuário **removeu** todos os AI/REA,
      criamos um clone “fantasma” (archived_ai = 1) apenas com o(s) AI/REA,
      refeições zeradas, para fins de estatística.
    """
    if (new_start is None) != (new_end is None):
        raise ValueError("new_start e new_end precisam ser fornecidos em conjunto.")

    if new_start is not None:
        start_qt = QTime.fromString(new_start, "HH:mm")
        end_qt   = QTime.fromString(new_end,   "HH:mm")
        if not (start_qt.isValid() and end_qt.isValid()):
            raise ValueError("Horário inválido; use o formato HH:mm.")

    with get_conn() as c:
        cur = c.cursor()
        row = cur.execute(
            "SELECT demands,start_time,end_time,encaminhamento,"
            "       desjejum||','||lunch||','||snack||','||dinner "
            "FROM records WHERE id=?", (pid,)
        ).fetchone()

        if row is None:
            raise RuntimeError("ID não encontrado.")

        (old_dem, old_start, old_end, old_enc, old_vals) = row

        # ---------- 1) eventualmente cria o clone ------------------
        old_tokens = [t.strip() for t in (old_dem or "").split(",") if t.strip()]
        old_ai     = [t for t in old_tokens if t.startswith(("AI", "REA"))]
        new_ai     = [t for t in (new_demands or "").split(",") if t.strip().startswith(("AI", "REA"))]

        if old_ai and not new_ai:
            # houve remoção total de AI/REA  →  clonar
            d_b, d_l, d_s, d_d = (0, 0, 0, 0)     # zera refeições
            now = QTime.currentTime().toString("HH:mm")

            cur.execute("""
                INSERT INTO records (
                    patient_name, demands, reference_prof, date,
                    enter_sys, enter_inf,
                    observations, encaminhamento,
                    desjejum, lunch, snack, dinner,
                    start_time, end_time,
                    archived_ai
                )
                SELECT patient_name, ?, reference_prof, date,
                       enter_sys, ?, observations, encaminhamento,
                       ?, ?, ?, ?,
                       start_time, end_time,
                       1
                  FROM records WHERE id=?
            """, (", ".join(old_ai), now, d_b, d_l, d_s, d_d, pid))

        # ---------- 2) log + UPDATE normal -------------------------
        cur.execute("""
            INSERT INTO demand_log (record_id, ts, old_demands, new_demands)
            VALUES (?,?,?,?)
        """, (pid, datetime.now().strftime("%d/%m %H:%M"), old_dem, new_demands))

        cur.execute("""
            UPDATE records
               SET demands=?, start_time=?, end_time=?, encaminhamento=?
             WHERE id=?
        """, (new_demands, new_start, new_end, new_enc, pid))


        c.commit()
        
def has_edit_log(pid):
    with get_conn() as c:
        return (
            c.execute("SELECT 1 FROM meal_log   WHERE record_id=? LIMIT 1", (pid,)).fetchone()
            or c.execute("SELECT 1 FROM demand_log WHERE record_id=? LIMIT 1", (pid,)).fetchone()
        ) is not None
        


def leave_record(pid, left_sys, left_inf):
    with get_conn() as c:
        row = c.execute(
            "SELECT enter_inf,left_sys FROM records WHERE id=?",
            (pid,),
        ).fetchone()

        if row is None:
            raise RuntimeError("ID não encontrado.")

        enter_inf, already_left = row

        if already_left:
            raise ValueError("Paciente já está na aba “Saíram”.")

        enter_time = QTime.fromString(enter_inf, "HH:mm")
        left_time  = QTime.fromString(left_inf,  "HH:mm")

        if enter_time.isValid() and left_time.isValid() and left_time < enter_time:
            raise ValueError("Horário de saída não pode ser anterior ao horário de entrada.")

        c.execute(
            "UPDATE records SET left_sys=?,left_inf=? WHERE id=?",
            (left_sys, left_inf, pid),
        )
        c.commit()

def reactivate_from(pid, enter_sys, enter_inf):
    with get_conn() as c:
        row = c.execute("SELECT left_sys FROM records WHERE id=?", (pid,)).fetchone()
        if row is None:
            raise RuntimeError("ID não encontrado.")

        left_sys, = row
        if left_sys is None:
            raise ValueError("Registro já está ativo; não é possível reativar duas vezes.")

        c.execute(
            """
            UPDATE records
               SET enter_sys=?, enter_inf=?, left_sys=NULL, left_inf=NULL, archived_ai=0
             WHERE id=?
            """,
            (enter_sys, enter_inf, pid),
        )
        c.commit()
        return pid

def has_meal_log(pid)->bool:
    with get_conn() as c:
        return c.execute("SELECT 1 FROM meal_log WHERE record_id=? LIMIT 1",(pid,)).fetchone() is not None




def counts(date_iso):
    with get_conn() as c:
        dj,al,la,ja,total,acolh=c.execute("""
        SELECT SUM(desjejum),SUM(lunch),SUM(snack),SUM(dinner),
               COUNT(*),
               SUM(CASE WHEN encaminhamento IS NOT NULL THEN 1 ELSE 0 END)
        FROM records WHERE date=? AND left_sys IS NULL AND archived_ai=0""",(date_iso,)).fetchone()
    return {"desj":dj or 0,"lunch":al or 0,"snack":la or 0,
            "dinner":ja or 0,"total de Pacientes":total or 0,"acolh":acolh or 0}


# ───────────────────────────────────────────── Busca Avançada
class SearchDialog(QDialog):
    """Diálogo de pesquisa avançada com listas DINÂMICAS de Demanda e Encaminhamento,
       baseadas no intervalo de datas escolhido pelo usuário."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Buscar registros 🔍")
        lay = QFormLayout(self)

        # —— texto livre (nome / profissional) ————————————————
        self.txt_name = QLineEdit()
        self.txt_prof = QLineEdit()
        lay.addRow("Nome do paciente contém:", self.txt_name)
        lay.addRow("Profissional contém:",     self.txt_prof)

        # —— combos vazios (serão populados mais abaixo) ————————
        self.cmb_dmd = QComboBox()
        self.cmb_enc = QComboBox()

        # —— intervalo de datas ——————————————————————————————
        self.d_ini = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.d_end = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.d_ini.setDate(QDate.currentDate().addMonths(-1))
        self.d_end.setDate(QDate.currentDate())

        # quando mudar qualquer data → recarrega listas
        self.d_ini.dateChanged.connect(lambda _: self._populate_combos())
        self.d_end.dateChanged.connect(lambda _: self._populate_combos())

        lay.addRow("Tipo de atendimento:",     self.cmb_dmd)
        lay.addRow("Tipo de encaminhamento:",  self.cmb_enc)
        lay.addRow("De:", self.d_ini)
        lay.addRow("Até:", self.d_end)

        # —— check-boxes de refeições ————————————————————————
        self.chk_b = QCheckBox("Fez Desjejum 🥞")
        self.chk_l = QCheckBox("Fez Almoço 🥗")
        self.chk_s = QCheckBox("Fez Lanche 🥪")
        self.chk_d = QCheckBox("Fez Janta 🍛")
        for w in (self.chk_b, self.chk_l, self.chk_s, self.chk_d):
            lay.addRow(w)

        # —— modo avançado (tokenizar texto) ————————————————
        self.chk_adv = QCheckBox("Busca avançada (tokenizar nome/prof.)")
        lay.addRow(self.chk_adv)

        lay.addRow("", QPushButton("Buscar ✅", clicked=self.accept))

        # primeira carga das listas
        self._populate_combos()

    # ---------- helpers dinâmicos ----------------------------------

    def _date_iso_range(self):
        to_iso = lambda qdate: qdate.toString("yyyyMMdd")
        return to_iso(self.d_ini.date()), to_iso(self.d_end.date())

    def _populate_combos(self):
        """Recarrega opções de demanda/encaminhamento segundo intervalo de datas."""
        d0, d1 = self._date_iso_range()

        # ----- Demanda ------------------------------------------------
        self.cmb_dmd.blockSignals(True)
        self.cmb_dmd.clear()
        self.cmb_dmd.addItem("— Qualquer —", "")

        seen = set()
        with get_conn() as c:
            for (demands,) in c.execute("""
                 SELECT DISTINCT demands FROM records
                  WHERE (substr(date,7,4)||substr(date,4,2)||substr(date,1,2))
                        BETWEEN ? AND ? AND demands IS NOT NULL
            """, (d0, d1)):
                for tok in demands.split(","):
                    tok = tok.strip()
                    if not tok:
                        continue
                    code = tok.split(" ")[0]      # pega só “C”, “AN”, “AI”… (1ª palavra)
                    seen.add(code)

        for code in sorted(seen):
            self.cmb_dmd.addItem(code, code)
        self.cmb_dmd.blockSignals(False)


        # — Encaminhamento —
        self.cmb_enc.blockSignals(True)
        self.cmb_enc.clear()
        self.cmb_enc.addItem("— Qualquer —", "")
        with get_conn() as c:
            encs = [e for (e,) in c.execute("""
                    SELECT DISTINCT encaminhamento FROM records
                     WHERE encaminhamento IS NOT NULL
                       AND (substr(date,7,4)||substr(date,4,2)||substr(date,1,2))
                           BETWEEN ? AND ?
            """, (d0, d1))]
        for enc in sorted(encs):
            self.cmb_enc.addItem(enc, enc)
        self.cmb_enc.blockSignals(False)

    # ---------- devolve filtros escolhidos --------------------------

    def filters(self):
        return dict(
            name  = self.txt_name.text().strip(),
            prof  = self.txt_prof.text().strip(),
            dmd   = self.cmb_dmd.currentData(),   # "" se “Qualquer”
            enc   = self.cmb_enc.currentData(),
            d_ini = self.d_ini.date().toString("dd/MM/yyyy"),
            d_end = self.d_end.date().toString("dd/MM/yyyy"),
            b   = self.chk_b.isChecked(),
            l   = self.chk_l.isChecked(),
            s   = self.chk_s.isChecked(),
            d   = self.chk_d.isChecked(),
            adv = self.chk_adv.isChecked(),
        )


# ───────────────────────────────────────────── GUI
class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        init_db()

        self.setWindowTitle("Registro de Pacientes da recepção - Caps AD III Paulo da Portela v3.5 🗒️")
        self.resize(800, 780)
        self.start_time = self.end_time = self.enc = None

        # ─── 1. Central widget + foto de fundo ─────────────────────────
        import os, sys
        central = QWidget(self)
        central.setObjectName("bg")
        self.setCentralWidget(central)

        def _img_path(nome: str) -> str:
            base = getattr(sys, "_MEIPASS", os.path.abspath("."))
            return os.path.join(base, nome).replace("\\", "/")

        # imagem cobre tudo (estica proporcional)
        self.setStyleSheet(f"""
            /* ——— Fundo grandão ——— */
            #bg {{
                border-image: url("{_img_path('fundo_caps.jpg')}") 0 0 0 0 stretch stretch;
            }}

            /* Texto branco SOMENTE dentro do painel principal (#bg)       */
            #bg QLabel,
            #bg QCheckBox,
            #bg QRadioButton,
            #bg QGroupBox:title {{
                color: white;
            }}

            /* Tudo que precisa ser preto em qualquer lugar da app          */
            QPushButton,            /* Botões: Registrar, Marcar saída, etc.        */
            QTabBar::tab,           /* Abas Ativos 🔵, Desjejum 🥞 ...               */
            QHeaderView::section,   /* Cabeçalhos da tabela                         */
            QMessageBox QLabel,     /* Texto dos pop-ups (Histórico ✏️)             */
            QDialog QLabel,         /* Labels nos diálogos (Editar Refeições 🍽️…)  */
            QDialog QCheckBox       /* Caixinhas dentro do Editar Refeições         */
            {{
                color: black;
            }}
        """)


        # Layout raiz
        outer = QVBoxLayout(central)

        # ─── 2. Logo opcional - antigo ──────────────────────────────────────────
        #if Path("OIG.jpeg").exists():
          #  logo = QLabel(alignment=Qt.AlignCenter)
        #    logo.setPixmap(QPixmap("OIG.jpeg").scaled(
           #     60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation))
          #  outer.addWidget(logo)

        # ─── 3. Seleção de data ───────────────────────────────────────
        row_date = QHBoxLayout(); outer.addLayout(row_date)
        row_date.addWidget(QLabel("Data 📅:"))
        self.date = QDateEdit(QDate.currentDate(), calendarPopup=True,
                              displayFormat="dd/MM/yyyy")
        self.date.dateChanged.connect(lambda _: (self._update_demand_filter_combo(),
                                                 self.refresh()))

        row_date.addWidget(self.date); row_date.addStretch()

        # ─── 4. Formulário ────────────────────────────────────────────
        form = QVBoxLayout(); outer.addLayout(form)

        LINE_W = 350   # largura máx. dos campos de texto (ajuste à vontade)
        BTN_W  = 180   # largura fixa do botão Registrar

        # ——— Campos de texto mais curtos ———
        self.txt_name = MyLineEdit(); self.txt_name.setMaximumWidth(LINE_W)
        self.txt_ref  = MyLineEdit(); self.txt_ref.setMaximumWidth(LINE_W)
        self.txt_obs  = MyLineEdit(); self.txt_obs.setMaximumWidth(LINE_W)

        form.addWidget(QLabel("Paciente 🙂:"))
        form.addWidget(self.txt_name, alignment=Qt.AlignLeft)

        form.addWidget(QLabel("Demanda 📋:"))

        self.dem_cb = []
        dem_list = [d for d in DEMAND_LIST if d != "AN Saiu"]   # esconde AN Saiu

        for i, d in enumerate(dem_list):
            if i % 5 == 0:
                row = QHBoxLayout()
                form.addLayout(row)

            cb = QCheckBox(d)
            self.dem_cb.append(cb)
            row.addWidget(cb)

            # TODAS passam pela mesma lógica de exclusividade AI/REA
            cb.stateChanged.connect(self._ai)

            # regras específicas mantidas
            if d == "C":
                cb.stateChanged.connect(self._c)
            if d == "AN":
                cb.stateChanged.connect(self._an)
            if d in ("R", "M", "RM"):         # para a regra R+M→RM
                cb.stateChanged.connect(self._rm_logic)           

        form.addWidget(QLabel("Refeições 🍽️:"))
        self.chk_b = QCheckBox("Desjejum 🥞")
        self.chk_l = QCheckBox("Almoço 🥗")
        self.chk_s = QCheckBox("Lanche 🥪")
        self.chk_d = QCheckBox("Janta 🍛")
        for chk in (self.chk_b, self.chk_l, self.chk_s, self.chk_d):
            form.addWidget(chk, alignment=Qt.AlignLeft)

        self.lbl_conv = QLabel(); self.lbl_enc = QLabel()
        form.addWidget(self.lbl_conv); form.addWidget(self.lbl_enc)

        form.addWidget(QLabel("Prof. ref. 🧑‍⚕️:"))
        form.addWidget(self.txt_ref, alignment=Qt.AlignLeft)

        form.addWidget(QLabel("Observações 📝:"))
        form.addWidget(self.txt_obs, alignment=Qt.AlignLeft)

# ——— Botão Registrar curtinho e à esquerda ———
        btn_reg = QPushButton("Registrar 📝", clicked=self.register)
        btn_reg.setFixedWidth(BTN_W)
        outer.addWidget(btn_reg, alignment=Qt.AlignLeft)


# ─── 5. Dashboard ────────────────────────────────────────────
        dash = QHBoxLayout(); outer.addLayout(dash)

        # ícone, coluna boolean do BD e rótulo human-readable
        _meal_info = {
            "desj":  ("🥞", "desjejum", "Desjejum"),
            "lunch": ("🥗", "lunch",    "Almoço"),
            "snack": ("🥪", "snack",    "Lanche"),
            "dinner":("🍛", "dinner",   "Janta"),
        }

        self.dash_lbls = {}   # números
        self.dash_btns = {}   # ícones clicáveis

        # 5. Dashboard (substitua o bloco que cria os ícones)

        from functools import partial

        for key, (ico, _col, _tit) in _meal_info.items():
            btn = QPushButton(ico)
            btn.setFlat(True)                # sem moldura
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("font-size: 24px;")  # tamanho do emoji

            btn.clicked.connect(partial(self._copy_meal, key))
            self.dash_btns[key] = btn

            num = QLabel("0", alignment=Qt.AlignCenter)
            self.dash_lbls[key] = num

            col = QVBoxLayout()
            col.addWidget(btn, alignment=Qt.AlignCenter)
            col.addWidget(num, alignment=Qt.AlignCenter)
            dash.addLayout(col)



        # ─── 6. Abas ────────────────────────────────────────────────
        self.tabs = QTabWidget(); outer.addWidget(self.tabs)
                # depois de criar self.tabs = QTabWidget()
        row_filtro = QHBoxLayout(); outer.addLayout(row_filtro)

        # combo de demanda
        self.cmb_dmd_filter = QComboBox()
        self.cmb_dmd_filter.addItem("— Todas as demandas —", "")
        for d in DEMAND_LIST:
            if d not in ("AN Saiu"):            # não faz sentido filtrar por essa
                self.cmb_dmd_filter.addItem(d, d)
                        # ...depois de adicionar self.cmb_dmd_filter e antes do row_filtro.addWidget(...)
                self._update_demand_filter_combo()

        row_filtro.addWidget(self.cmb_dmd_filter)

        # botão de ordenação
        self.cmb_order = QComboBox()
        self.cmb_order.addItems([
            "Ordem original (ID desc.)",        # 0
            "Nome do paciente (A-Z)",           # 1
            "Profissional (A-Z)"                # 2
        ])
        row_filtro.addWidget(self.cmb_order)

        btn_aplicar = QPushButton("Aplicar filtro 🔄")
        row_filtro.addWidget(btn_aplicar); row_filtro.addStretch()
        btn_aplicar.clicked.connect(self.refresh)  # refresh já usa os filtros
        self.btn_export_dia = QPushButton("Exportar dia 📤")
        row_filtro.addWidget(self.btn_export_dia)
        self.btn_export_dia.clicked.connect(self.exportar_dia)



        self.tbl_all    = self._tbl("Ativos 🔵")
        self.tbl_break  = self._tbl("Desjejum 🥞")
        self.tbl_lunch  = self._tbl("Almoço 🥗")
        self.tbl_snack  = self._tbl("Lanche 🥪")
        self.tbl_dinner = self._tbl("Janta 🍛")
        self.tbl_acolh = self._tbl(
            "Acolhimentos 🤝",
            headers=[
                "ID", "Paciente", "Demanda", "Prof.", "Enc.", "Clone?",
                "Entrou", "≈Entrou", "Saiu", "≈Saiu"
            ]

        )

        self.tbl_left   = self._tbl("Saíram ⚪")
        # NOVO:
        self.tbl_cons_day   = self._cons_tbl("Consolidado (dia)")
        self.tbl_cons_total = self._cons_tbl("Consolidado (geral)")

        self.patient_tables = [
            self.tbl_all, self.tbl_break, self.tbl_lunch, self.tbl_snack,
            self.tbl_dinner, self.tbl_acolh, self.tbl_left,
        ]

        # ─── 7. Botões de ação ───────────────────────────────────────
        row_btn = QHBoxLayout(); outer.addLayout(row_btn)
        self.btn_leave = QPushButton("Marcar saída 🚪", clicked=self.leave)
        row_btn.addWidget(self.btn_leave)
        row_btn.addWidget(QPushButton("Reativar 🔄",    clicked=self.activate))
        row_btn.addWidget(QPushButton("Editar refeições 🍽️", clicked=self.edit_meals))
        row_btn.addWidget(QPushButton("Pesquisar 🔍",  clicked=self.search))
        row_btn.addWidget(QPushButton("Importar Excel 📥", clicked=self.import_excel))
        row_btn.addWidget(QPushButton("⚙️ Reparar dados antigos", clicked=self._run_fix))
        row_btn.addWidget(QPushButton("Editar registro 📝",  clicked=self.edit_record))
        row_btn.addWidget(QPushButton("Observações 🔍",      clicked=self._show_observations))
        row_btn.addWidget(QPushButton("Backup ☁️",
                              clicked=lambda: backup_now(self)))





        self.tabs.currentChanged.connect(self._update_leave_button_state)
        self._update_leave_button_state()
        row_btn.addStretch()

        # ─── 8. Primeira atualização ─────────────────────────────────
        self.refresh()

        # ---------- backup automático a cada 2 horas -----------------
        self._bk_timer = QTimer(self)
        self._bk_timer.timeout.connect(lambda: backup_now(self))
        self._bk_timer.start(2 * 60 * 60 * 1000)      # 2 h em milissegundos

    # ───────────────────────────────────────────────
    #  BACKUP AO FECHAR O APLICATIVO
    # ───────────────────────────────────────────────
    def closeEvent(self, ev):
        """
        Executa um backup final antes de encerrar o programa.
        Se o usuário cancelar a correção de pasta, ainda assim fecha.
        """
        try:
            backup_now(self)        # faz o backup na hora do fechamento
        except Exception as exc:    # mostra erro mas não impede o encerramento
            QMessageBox.critical(self, "Falha no backup", str(exc))
        super().closeEvent(ev)      # continua o fluxo normal


    def exportar_dia(self):
        iso = self.date.date().toString("dd/MM/yyyy")
        pacientes = self.fetch(iso, "AND left_sys IS NULL")  # já filtra/ordena
        acolh     = self._fetch_acolh(iso)              # AI/REA ativos

        if not pacientes and not acolh:
            QMessageBox.information(self, "Exportar", "Nenhum registro no dia.")
            return

        # --- montar DataFrames ---
        cols_main = ["ID","Paciente","Demanda","Profissional",
                     "Entrou≈", "Saiu≈"]
        main_rows = [
            [id_, nome, dmd, prof, enter_inf, left_inf]
            for (id_, nome, dmd, prof, enter_sys, enter_inf,
                 left_sys, left_inf) in pacientes
        ]

        cols_ai  = ["ID","Paciente","Demanda","Profissional",
                    "Encaminhamento", "Entrou≈", "Saiu≈"]
        ai_rows = []
        for (id_, nome, dmd, prof, enc, _arc,   # _arc = archived_ai
             enter_sys, enter_inf, left_sys, left_inf) in acolh:
            ai_rows.append([id_, nome, dmd, prof, enc, enter_inf, left_inf])


        # ------------------------------------------------------------
        # GRAVAR EM EXCEL  – salva direto no Desktop e trata erros
        # ------------------------------------------------------------
        try:
            # 1) pasta Desktop (Windows/ macOS/ Linux)
            desktop = Path.home() / "Desktop"
            # 2) se for Windows em PT-BR (“Área de Trabalho”)
            if not desktop.exists():
                desktop = Path.home() / "Área de Trabalho"
            # 3) fallback: mesma pasta do script
            if not desktop.exists():
                desktop = Path(__file__).parent

            nome_arquivo = f"pacientes_{iso.replace('/','-')}.xlsx"
            caminho = desktop / nome_arquivo

            with pd.ExcelWriter(caminho, engine="xlsxwriter") as writer:
                if main_rows:
                    pd.DataFrame(main_rows, columns=cols_main)\
                        .to_excel(writer, sheet_name="Pacientes", index=False)
                if ai_rows:
                    pd.DataFrame(ai_rows, columns=cols_ai)\
                        .to_excel(writer, sheet_name="AI_REA",  index=False)

            QMessageBox.information(
                self, "Exportado ✅",
                f"Arquivo salvo em:\n{caminho}"
            )

        except Exception as exc:
            QMessageBox.critical(
                self, "Erro ao exportar ❌",
                f"Não foi possível gerar o arquivo:\n{exc}"
            )


        

    # -------- executa o script de reparo -----------------------------
    def _run_fix(self):
        _fix_old_imports(self)
        self.refresh()       


    # ------------------------------------------------------------
    #  MÉTRICAS CONSOLIDADAS (inclui encaminhamentos)
    # ------------------------------------------------------------
    def _metrics(self, rows):
        """
        Recebe uma lista de registros (SELECT * FROM records)
        e devolve contagens:
          • Demanda (A, R, M, …, AN)
          • Refeições (desj, alm, lan, jan)
          • Encaminhamentos (cada tipo recebido em r[10])
        """
        # códigos de demanda que nos interessam
        codes = [
            "A", "R", "M", "C", "RM",
            "Grupos/Eventos", "Outros", "AI", "REA", "AN"
        ]

        data = {                # contadores básicos
            "total de Pacientes": 0, "acolh": 0,
            "desj": 0, "alm": 0, "lan": 0, "jan": 0,
        }
        # inicia todos os códigos de demanda em zero
        data.update({c: 0 for c in codes})

        for r in rows:
            is_clone = bool(r[17])
            if not is_clone:
                data["total de Pacientes"] += 1

            # ----- DEMANDAS --------------------------------------------------
            dmd_tokens = [s.strip() for s in (r[2] or "").split(",")]
            # se for “AN Saiu” não entra na contagem
            dmd_tokens = [tok for tok in dmd_tokens if tok.strip() != "AN Saiu"]

            for code in codes:
                if any(tok.startswith(code) for tok in dmd_tokens):
                    data[code] += 1

            # ----- REFEIÇÕES (ignora clones AI) --------------------
            # 3) _metrics()
            if not is_clone:             # clones não contam refeições
                if r[11]: data["desj"] += r[11]
                if r[12]: data["alm"]  += r[12]
                if r[13]: data["lan"]  += r[13]
                if r[14]: data["jan"]  += r[14]



            # ----- ENCAMINHAMENTOS ------------------------------------------
            enc = (r[10] or "").strip()      # coluna encaminhamento
            if enc:
                data["acolh"] += 1           # contador geral de acolhimentos
                data.setdefault(enc, 0)      # cria chave se ainda não existe
                data[enc] += 1               # soma 1 para esse tipo

        return data

    
    def _copy_meal(self, key):
        """
        Copia para a área de transferência:
            Nome  (demanda OU intervalo C)  —  horário
        Ex.:
            - João (A) — 09:15
            - Maria (C 10:00-12:30) — s/horário
        """
        col_map   = {"desj": "desjejum", "lunch": "lunch",
                     "snack": "snack",   "dinner": "dinner"}
        title_map = {"desj": "Desjejum", "lunch": "Almoço",
                     "snack": "Lanche",  "dinner": "Janta"}

        col_name = col_map[key]
        pretty   = title_map[key]
        date_iso = self.date.date().toString("dd/MM/yyyy")

        # buscamos também demands, start_time e end_time
        with get_conn() as c:
            rows = c.execute(f"""
                SELECT patient_name,
                       demands, start_time, end_time,
                       enter_inf
                  FROM records
                 WHERE date=? AND {col_name}=1 AND left_sys IS NULL
                 ORDER BY patient_name
            """, (date_iso,)).fetchall()

        if not rows:
            QTimer.singleShot(
                0,
                lambda: QMessageBox.information(
                    self, "Nada a copiar",
                    f"Nenhum paciente marcado para {pretty.lower()}.")
            )
            return

        def demanda_format(demands, st, et):
            """
            • Se tiver 'C', devolve 'C HH:mm-HH:mm'
            • Caso contrário, devolve o primeiro código (A, R, RM…)
            """
            if demands and "C" in [tok.strip().split(" ")[0] for tok in demands.split(",")]:
                if st and et:
                    return f"C {st}-{et}"
                # se o intervalo não estiver nas colunas, tenta pegar do texto 'C (...)'
                for tok in demands.split(","):
                    tok = tok.strip()
                    if tok.startswith("C"):
                        return tok
                return "C"
            # não sendo convivência, pega o 1º token
            return (demands.split(",")[0].strip().split(" ")[0]) if demands else "—"

        body = []
        for nome, dmd, st, et, hora in rows:
            d_fmt  = demanda_format(dmd, st, et)
            h_fmt  = hora or "s/horário"
            body.append(f"- {nome} ({d_fmt}) — {h_fmt}")

        text = f"🍽️ *{pretty}* – {len(rows)} pacientes:\n" + "\n".join(body)

        def _do_copy():
            cb = QApplication.clipboard()
            cb.clear(mode=cb.Clipboard)
            cb.setText(text, mode=cb.Clipboard)
            QMessageBox.information(
                self, "Copiado ✅",
                "Mensagem copiada!\nAgora é só *Ctrl + V* no grupo pra cobrar a galera 😄"
            )

        QTimer.singleShot(0, _do_copy)





    # ------------------------------------------------------------
    # 2. PESQUISA AVANÇADA
    # ------------------------------------------------------------
    def search(self):
        dlg = SearchDialog(self)
        if dlg.exec_() == 0:       # usuário cancelou
            return

        f = dlg.filters()

        # ---------- intervalo de datas ----------
        # "01/08/2023" -> "20230801"
        def to_iso(d):
            return d[6:10] + d[3:5] + d[0:2]

        sql = """
            SELECT date, patient_name, reference_prof,
                   desjejum, lunch, snack, dinner,
                   enter_sys, left_sys
            FROM records
            WHERE (substr(date,7,4)||substr(date,4,2)||substr(date,1,2))
                  BETWEEN ? AND ?
        """
        params = [to_iso(f["d_ini"]), to_iso(f["d_end"])]

        # ---------- filtros de texto / combo ----------
        def add_tokens(field, value):
            nonlocal sql, params           # ← move pra primeira linha!
            for token in value.split():
                sql += f" AND {field} LIKE ?"
                params.append(f"%{token}%")

        # nome / profissional
        if f["adv"]:
            if f["name"]: add_tokens("patient_name",   f["name"])
            if f["prof"]: add_tokens("reference_prof", f["prof"])
        else:
            if f["name"]:
                sql += " AND patient_name LIKE ?"
                params.append(f"%{f['name']}%")
            if f["prof"]:
                sql += " AND reference_prof LIKE ?"
                params.append(f"%{f['prof']}%")

        # demanda
        if f["dmd"]:
            sql += " AND demands LIKE ?"
            params.append(f"%{f['dmd']}%")

        # encaminhamento
        if f["enc"]:
            sql += " AND encaminhamento = ?"
            params.append(f["enc"])

        # refeições
        if f["b"]: sql += " AND desjejum = 1"
        if f["l"]: sql += " AND lunch    = 1"
        if f["s"]: sql += " AND snack    = 1"
        if f["d"]: sql += " AND dinner   = 1"

        # ---------- executa ----------
        sql += " ORDER BY (substr(date,7,4)||substr(date,4,2)||substr(date,1,2)) DESC, patient_name"
        with get_conn() as c:
            rows = c.execute(sql, params).fetchall()

        if not rows:
            QMessageBox.information(self, "Busca", "Nenhum resultado encontrado.")
            return

        # ---------- mostra ----------
        # —–– resumo de filtros para o título —–—
        resumo = [f"{f['d_ini']} → {f['d_end']}"]
        if f["dmd"]: resumo.append(f"Demanda: {f['dmd']}")
        if f["enc"]: resumo.append(f"Enc.: {f['enc']}")
        if f["name"]: resumo.append(f"Nome≈“{f['name']}”")
        if f["prof"]: resumo.append(f"Prof≈“{f['prof']}”")

        res = QDialog(self)
        res.setWindowTitle(" ; ".join(resumo) + f"   — {len(rows)} registros")

        tbl = QTableWidget(len(rows), 9, res)
        headers = ["Data", "Paciente", "Prof.", "Desj.",
                   "Alm.", "Lan.", "Jan.", "Entrou", "Saiu"]
        tbl.setHorizontalHeaderLabels(headers)

        # também preparamos uma lista p/ exportação
        export_rows = []
        for r, row in enumerate(rows):
            row_list = list(row)
            for c in (3, 4, 5, 6):              # 0/1 → ✔️/—
                row_list[c] = "✔️" if row_list[c] else ""
            export_rows.append(row_list)

            for c, val in enumerate(row_list):
                tbl.setItem(r, c, QTableWidgetItem(str(val)))

        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        # ----- botão Exportar p/ Excel -----
        def _export():
            df = pd.DataFrame(export_rows, columns=headers)
            nome = f"relatorio_{to_iso(f['d_ini'])}_{to_iso(f['d_end'])}.xlsx"
            caminho = Path(__file__).with_name(nome)
            try:
                df.to_excel(caminho, index=False)
                QMessageBox.information(res, "Exportado",
                                        f"Arquivo salvo em\n{caminho.name}")
            except Exception as exc:
                QMessageBox.critical(res, "Erro ao exportar", str(exc))

        btn_exp = QPushButton("Exportar para Excel 📤", clicked=_export)

        lay = QVBoxLayout(res)
        lay.addWidget(tbl)
        lay.addWidget(btn_exp, alignment=Qt.AlignRight)

        res.resize(800, 460)
        res.exec_()




    # -------- tabela helper
    def _tbl(self, title, headers=None):
        """
        Cria uma QTableWidget padrão.
        Se 'headers' for passado, usa essa lista; caso contrário usa as 8 colunas base.
        """
        if headers is None:
            headers = ["ID","Paciente","Demanda","Prof.",
                       "Entrou","≈Entrou","Saiu","≈Saiu"]

        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.itemDoubleClicked.connect(self.show_history)
        self.tabs.addTab(t, title)
        return t


    def _cons_tbl(self, title):
        t = QTableWidget(0, 2)
        t.setHorizontalHeaderLabels(["Métrica", "Valor"])
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tabs.addTab(t, title)
        return t
    

    def _fill(self, tbl, data, include_enc=False):
        tbl.setRowCount(len(data))
        for r, row in enumerate(data):
            pid = row[0]
            edited_flag = "🖊️" if has_edit_log(pid) else ""
            for c, val in enumerate(row):
                if c == 1:  # coluna “Paciente”
                    val = f"{val}{edited_flag}"
                item = QTableWidgetItem("" if val is None else str(val))
                if include_enc and row[5]:          # 4 == archived_ai
                    item.setForeground(Qt.gray)
                    item.setFlags(item.flags() & ~(Qt.ItemIsSelectable | Qt.ItemIsEnabled))
                
                tbl.setItem(r, c, item)
        tbl.resizeRowsToContents()



    # ------------------------------------------------------------
    #  Preenche a tabela de consolidados (esconde zeros)
    # ------------------------------------------------------------
    def _fill_cons(self, tbl, data):
        """
        Exibe apenas as métricas cujo valor seja > 0
        e ordena alfabeticamente a chave.
        """
        # filtra fora as métricas zeradas
        items = [(k, v) for k, v in sorted(data.items()) if v > 0]

        tbl.setRowCount(len(items))
        for r, (k, v) in enumerate(items):
            tbl.setItem(r, 0, QTableWidgetItem(k))
            tbl.setItem(r, 1, QTableWidgetItem(str(v)))

        tbl.resizeRowsToContents()

                    
    # ------------------------------------------------------------
    #  Helper: busca linhas da aba “Acolhimentos 🤝” com encaminhamento
    # ------------------------------------------------------------
    def _fetch_acolh(self, date_iso):
        """
        Retorna registros do dia com encaminhamento (AI/REA) ainda ativos.
        Formato de retorno já combina com as 9 colunas da aba:
        ID | Paciente | Demanda | Prof. | Encaminhamento |
        Entrou | ≈Entrou | Saiu | ≈Saiu
        """
        sql = """
            SELECT id, patient_name, demands, reference_prof,
                   encaminhamento, archived_ai,
                   enter_sys, enter_inf, left_sys, left_inf
            FROM records
            WHERE date = ?
              AND encaminhamento IS NOT NULL
              AND archived_ai = 0
              AND left_sys IS NULL

            ORDER BY id DESC
        """
        with get_conn() as c:
            return c.execute(sql, (date_iso,)).fetchall()

# ------------------------------------------------------------
#  REABERTURA AUTOMÁTICA – “AN”/“AN Entrou” do dia anterior
# ------------------------------------------------------------
    def _rollover_an(self, today_iso: str) -> None:
        """
        Duplica, para o dia ‘today_iso’, todos os pacientes que:
            • ainda NÃO têm left_sys (ou seja, continuam internados)
            • estavam marcados como  AN  ou  AN Entrou  no dia anterior.
        Regras:
            • Se era “AN Entrou”, vira “AN” no dia seguinte.
            • Não duplica se o paciente já existir na data de destino.
        """
        prev_iso = QDate.fromString(today_iso, "dd/MM/yyyy")\
                         .addDays(-1).toString("dd/MM/yyyy")

        with get_conn() as c:
            rows = c.execute("""
                SELECT patient_name, demands, reference_prof,
                       observations, encaminhamento,
                       desjejum, lunch, snack, dinner,
                       start_time, end_time
                  FROM records
                 WHERE date=? AND left_sys IS NULL
            """, (prev_iso,)).fetchall()

            for row in rows:
                (name, demands, ref, obs, enc,
                 b, l, s, d, st, en) = row

                # só interessa se houver “AN” ou “AN Entrou”
                toks = [t.strip() for t in (demands or "").split(",")]
                if not any(t.startswith("AN") for t in toks):
                    continue

                # já existe hoje?
                if c.execute("SELECT 1 FROM records WHERE patient_name=? AND date=? LIMIT 1",
                             (name, today_iso)).fetchone():
                    continue

                # troca “AN Entrou” → “AN”
                novo_toks = []
                for t in toks:
                    if t.startswith("AN Entrou"):
                        novo_toks.append("AN")
                    elif t.startswith("AN"):
                        novo_toks.append("AN")
                    else:
                        novo_toks.append(t)
                novo_demands = ", ".join(novo_toks)

                now = QTime.currentTime().toString("HH:mm")

                c.execute("""
                    INSERT INTO records (
                        patient_name, demands, reference_prof, date,
                        enter_sys, enter_inf,
                        observations, encaminhamento,
                        desjejum, lunch, snack, dinner,
                        start_time, end_time
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (name, novo_demands, ref, today_iso,
                      now, now, obs, enc,
                      b, l, s, d, st, en))
            c.commit()
     
    # ------------------------------------------------------------
    #  Importador de Excel (rápido + progress bar)
    # ------------------------------------------------------------
    def import_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolha o arquivo Excel",
            "", "Planilhas Excel (*.xlsx)")
        if not path:
            return

        try:
            wb = pd.read_excel(path, sheet_name=None, header=None)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha lendo Excel:\n{e}")
            return

        # ------------ conta linhas relevantes p/ barra ------------
        total_rows = 0
        for sh, df in wb.items():
            sh = str(sh).strip().lower()
            if sh in ("pacientes", "almoço", "lanche", "janta") or sh.startswith("acolh"):
                total_rows += df.dropna(how="all").shape[0]

        progress = QProgressDialog(
            "Importando dados…", "Cancelar", 0, total_rows, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumWidth(400)

        # mapping aba → flag refeição
        meal_flag = {
            "pacientes": None,
            "almoço":   "lunch",
            "lanche":   "snack",
            "janta":    "dinner",
        }

        processed = 0
        try:
            conn = get_conn()
            cur  = conn.cursor()
            cur.execute("BEGIN")           # transação ÚNICA

            for sheet_name, df in wb.items():
                sh = str(sheet_name).strip().lower()

                # ---------- PACIENTES / REFEIÇÕES ----------
                if sh in meal_flag:
                    flag = meal_flag[sh]
                    for _, row in df.iterrows():
                        if row.isna().all():
                            continue
                        nome  = str(row[0]).strip()
                        dmd   = str(row[1]).strip()
                        prof  = str(row[2]).strip()
                        data  = str(row[3]).strip()
                        hora  = str(row[4]).strip()
                        obs   = str(row[5]).strip()

                        if not nome or not data:
                            continue

                        # dentro do loop for _, row in df.iterrows():
                        pid = self._get_or_create(nome, data, cur)

                        # fetch dados atuais
                        row = cur.execute("SELECT demands FROM records WHERE id=?", (pid,)).fetchone()
                        if row is None:
                            raise RuntimeError("ID não encontrado.")

                        old_demands, = row
                        old_demands = old_demands or ""
                        new_demands = ", ".join(sorted({*(tok.strip() for tok in old_demands.split(",")),
                                                        *(tok.strip() for tok in dmd.split(","))} - {""}))

                        sets = ["demands=?", "reference_prof=?", "observations=?"]
                        vals = [new_demands, prof, obs]

                        # --- MARCA REFEIÇÃO conforme aba ---------------------------------
                        if flag:                           # almoço / lanche / janta
                            sets.append(f"{flag}=?")
                            vals.append(1)
                        else:                              # aba “Pacientes”
                            # se o horário começa com 09: marca Desjejum
                            if hora and str(hora)[:2] == "09":
                                sets.append("desjejum=?")
                                vals.append(1)

                        # --- ACERTA horário de entrada -----------------------------------
                        if hora and str(hora).lower() != "nan":
                            sets += ["enter_inf=?", "enter_sys=?"]   # grava nos dois campos
                            vals += [hora, hora]

                        vals.append(pid)
                        cur.execute(f"UPDATE records SET {', '.join(sets)} WHERE id=?", vals)


                        # progress bar
                        processed += 1
                        progress.setValue(processed)
                        QApplication.processEvents()
                        if progress.wasCanceled():
                            raise RuntimeError("Importação cancelada pelo usuário.")

                # ---------- ACOLHIMENTOS ----------
                elif sh.startswith("acolh"):
                    for _, row in df.iterrows():
                        if row.isna().all():
                            continue
                        nome  = str(row[0]).strip()
                        dmd   = str(row[1]).strip()
                        enc   = str(row[2]).strip()
                        prof  = str(row[3]).strip()
                        data  = str(row[4]).strip()
                        hora  = str(row[5]).strip()
                        obs   = str(row[6]).strip()

                        if not nome or not data:
                            continue

                        pid = self._get_or_create(nome, data, cur)

                        row = cur.execute(
                            "SELECT demands, encaminhamento FROM records WHERE id=?", (pid,)
                        ).fetchone()
                        if row is None:
                            raise RuntimeError("ID não encontrado.")

                        old_demands, old_enc = row
                        old_demands = old_demands or ""
                        new_demands = ", ".join(
                            sorted({*(tok.strip() for tok in old_demands.split(",")),
                                    *(tok.strip() for tok in dmd.split(","))} - {""})
                        )

                        cur.execute("""
                            UPDATE records
                            SET demands=?, encaminhamento=?, reference_prof=?,
                                observations=?, enter_inf=?
                            WHERE id=?
                        """, (new_demands, enc, prof, obs, hora, pid))

                        processed += 1
                        progress.setValue(processed)
                        QApplication.processEvents()
                        if progress.wasCanceled():
                            raise RuntimeError("Importação cancelada pelo usuário.")

            conn.commit()

        except Exception as exc:
            conn.rollback()
            QMessageBox.critical(self, "Erro", str(exc))
            return
        finally:
            conn.close()
            progress.close()

        self.refresh()
        QMessageBox.information(
            self, "Importação concluída",
            f"{processed} linhas importadas de\n{Path(path).name}")

    # --------- helper modificado: permite usar cur externo ----------
    def _get_or_create(self, name, date_iso, cur=None):
        own_conn = False
        if cur is None:
            own_conn = True
            conn = get_conn()
            cur  = conn.cursor()

        row = cur.execute(
            "SELECT id FROM records WHERE patient_name=? AND date=? AND left_sys IS NULL",
            (name, date_iso)
        ).fetchone()
        if row:
            pid = row[0]
        else:
            now = QTime.currentTime().toString("HH:mm")
            cur.execute("""
                INSERT INTO records (patient_name, date, enter_sys, enter_inf)
                VALUES (?,?,?,?)""", (name, date_iso, now, now))
            pid = cur.lastrowid
        if own_conn:
            conn.commit(); conn.close()
        return pid

    # ------------------------------------------------------------
    #  BUSCA DE REGISTROS (com filtro de demanda “exato” + ordenação C)
    # ------------------------------------------------------------
    def fetch(self, date_iso: str, extra: str = "", *, include_clones=False):
        """
        Retorna as linhas do dia `date_iso`, já respeitando:
          • filtro de demanda escolhido no combo (exato, sem engolir AN/M/RM…)
          • ordenação selecionada no combo de ordem
          • parâmetro `extra` passado pelos outros métodos (desjejum, lunch …)
        O formato de saída continua sendo 8 colunas:
            id, patient_name, demands, reference_prof,
            enter_sys, enter_inf, left_sys, left_inf
        """
        # ---------------- parâmetros fixos -----------------
        base_sql = f"""
            SELECT id, patient_name, demands, reference_prof,
                   enter_sys, enter_inf, left_sys, left_inf
              FROM records
             WHERE date = ? {extra}
        """
        params = [date_iso]

        # ───── novo trecho ─────
        if not include_clones:                 # padrão: esconder fantasmas
            base_sql += " AND archived_ai = 0"
        # ───────────────────────        

        # ---------------- filtro de demanda exata ----------
        wanted = (self.cmb_dmd_filter.currentData()
                  if hasattr(self, 'cmb_dmd_filter') else "")
        if wanted:
            # nada de LIKE "%A%" – vamos filtrar depois em Python
            pass  # só pegaremos tudo e filtraremos já no Python

        # ---------------- ordenação ------------------------
        order_idx = self.cmb_order.currentIndex() if hasattr(self, 'cmb_order') else 0

        if wanted == "C":                         # Convivência → ordenar por horário
            order_clause = "ORDER BY start_time, end_time, patient_name COLLATE NOCASE"
        else:                                     # demais opções
            order_map = {
                0: "ORDER BY id DESC",
                1: "ORDER BY patient_name COLLATE NOCASE",
                2: "ORDER BY reference_prof COLLATE NOCASE",
            }
            order_clause = order_map.get(order_idx, "ORDER BY id DESC")

        sql = f"{base_sql} {order_clause}"

        # ---------------- executa SQL ----------------------
        with get_conn() as c:
            rows = c.execute(sql, params).fetchall()

            # ---------------- filtro exato em Python -----------
        if wanted:
            def _match(demand_str: str) -> bool:
                """
                Regras:
                    • C  → qualquer token que comece com 'C'
                    • AN → qualquer token que comece com 'AN'
                    • Qualquer outro código → igualdade exata
                """
                for tok in (demand_str or "").split(","):
                    tok = tok.strip()
                    if wanted == "C" and tok.startswith("C"):
                        return True
                    if wanted == "AN" and tok.startswith("AN"):
                        return True
                    if tok == wanted:                     # ex.: 'AN Entrou'
                        return True
                return False

            rows = [r for r in rows if _match(r[2])]


        return rows



    # -------- checkbox logic
    def _ai(self, state):
        """
        Exclusividade AI/REA no formulário principal:
          – Se AI/REA ligar   ➜ desliga TODAS as demais demandas
          – Se outra ligar    ➜ desliga AI/REA
        """
        # 1) alguém acabou de mexer: refazemos o cenário completo
        ai_on = any(cb.isChecked() for cb in self.dem_cb
                    if cb.text() in ("AI", "REA"))
        other_on = any(cb.isChecked() for cb in self.dem_cb
                       if cb.text() not in ("AI", "REA"))

        # 2) aplica a regra
        if ai_on and other_on:
            if self.sender() and self.sender().text() in ("AI", "REA"):
                # AI/REA venceu  → limpa as outras
                for cb in self.dem_cb:
                    if cb.text() not in ("AI", "REA"):
                        cb.blockSignals(True)
                        cb.setChecked(False)
                        cb.blockSignals(False)
            else:
                # outra venceu  → limpa AI/REA + encaminhamento
                for cb in self.dem_cb:
                    if cb.text() in ("AI", "REA"):
                        cb.blockSignals(True)
                        cb.setChecked(False)
                        cb.blockSignals(False)
                self.enc = None
                self.lbl_enc.clear()

        # 3) se AI/REA acabou ligado, pedir/confirmar encaminhamento
        if any(cb.isChecked() for cb in self.dem_cb if cb.text() in ("AI", "REA")):
            if not self.enc:                       # ainda não tem enc. → pergunta
                dia = EncaminhamentoDialog(self)
                if dia.exec_():
                    self.enc = dia.choice()
                    self.lbl_enc.setText(f"Encaminhamento 🤝 {self.enc}")
                else:
                    # usuário cancelou → desmarca AI/REA
                    for cb in self.dem_cb:
                        if cb.text() in ("AI", "REA"):
                            cb.blockSignals(True)
                            cb.setChecked(False)
                            cb.blockSignals(False)
        else:
            self.enc = None
            self.lbl_enc.clear()



    def _an(self,state):
        val=state==Qt.Checked
        for chk in (self.chk_b,self.chk_l,self.chk_s,self.chk_d): chk.setChecked(val)

    def _c(self,state):
        if state!=Qt.Checked:
            self.start_time=self.end_time=None; self.lbl_conv.setText("")
            for chk in (self.chk_b,self.chk_l,self.chk_s,self.chk_d): chk.setChecked(False)
            return
        dlg=TimeIntervalDialog(self)
        if not dlg.exec_(): self.sender().setChecked(False); return
        self.start_time,self.end_time=dlg.interval()
        self.lbl_conv.setText(f"Convivência 🏠 {self.start_time}-{self.end_time}")
        t0=QTime.fromString(self.start_time,"HH:mm"); t1=QTime.fromString(self.end_time,"HH:mm")
        def covers(h): return t0<=h<=t1
        self.chk_b.setChecked(covers(HORARIOS["desjejum"]))
        self.chk_l.setChecked(covers(HORARIOS["almoco"]))
        self.chk_s.setChecked(covers(HORARIOS["lanche"]))
        self.chk_d.setChecked(covers(HORARIOS["janta"]))

    # ------------------------------------------------------------
    #  Não permitir combinações entre R, M e RM  (formulário novo)
    # ------------------------------------------------------------
    def _rm_logic(self, _=None):
        """
        Se mais de um entre R, M e RM ficar marcado, força apenas RM.
        """
        cb_r  = next(cb for cb in self.dem_cb if cb.text() == "R")
        cb_m  = next(cb for cb in self.dem_cb if cb.text() == "M")
        cb_rm = next(cb for cb in self.dem_cb if cb.text() == "RM")

        # quantidade de check-boxes ligados
        if sum([cb_r.isChecked(), cb_m.isChecked(), cb_rm.isChecked()]) >= 2:
            QMessageBox.information(
                self, "Demanda duplicada",
                "Para registrar *R* + *M* use apenas a opção **RM**."
            )

            # corta sinais, ajusta, reativa sinais
            for cb in (cb_r, cb_m, cb_rm):
                cb.blockSignals(True)

            cb_r.setChecked(False)
            cb_m.setChecked(False)
            cb_rm.setChecked(True)

            for cb in (cb_r, cb_m, cb_rm):
                cb.blockSignals(False)


        

    # -------- registro

    def register(self):
        # ── trava anti-AI/REA ──────────────────────────────────────────
        ai_on     = any(cb.isChecked() for cb in self.dem_cb if cb.text() in ("AI", "REA"))
        other_on  = any(cb.isChecked() for cb in self.dem_cb if cb.text() not in ("AI", "REA"))
        if ai_on and other_on:
            QMessageBox.warning(self, "Demanda inválida",
                                "AI/REA não pode ser combinada com outras demandas.")
            return
        # ───────────────────────────────────────────────────────────────

        try:
            name     = self.txt_name.text().strip()
            ref      = self.txt_ref.text().strip()
            obs      = self.txt_obs.text().strip()
            demands  = [cb.text() for cb in self.dem_cb if cb.isChecked()]

            if not name or not demands:
                raise ValueError("Nome e Demanda obrigatórios.")
            if not ref:
                raise ValueError("Profissional de referência faltando.")

            now = QTime.currentTime().toString("HH:mm")
            row = dict(
                patient_name = name,
                demands      = ", ".join(
                    d if d != "C" or not self.start_time
                      else f"C ({self.start_time}-{self.end_time})"
                    for d in demands
                ),
                reference_prof = ref,
                date           = self.date.date().toString("dd/MM/yyyy"),
                enter_sys      = now,
                enter_inf      = now,
                left_sys       = None,
                left_inf       = None,
                observations   = obs,
                encaminhamento = self.enc,
                desjejum = int(self.chk_b.isChecked()),
                lunch    = int(self.chk_l.isChecked()),
                snack    = int(self.chk_s.isChecked()),
                dinner   = int(self.chk_d.isChecked()),
                start_time = self.start_time,
                end_time   = self.end_time,
                archived_ai = 0,
            )

            add_record(row)
            self._clear()
            self.refresh()
            QMessageBox.information(self, "Sucesso 🎉", "Registro salvo!")

        except Exception as e:
            QMessageBox.critical(self, "Erro ❌", str(e))


    def _update_leave_button_state(self):
        is_patient_tab = self.tabs.currentWidget() in self.patient_tables
        self.btn_leave.setEnabled(is_patient_tab)


    # -------- saída
    def leave(self):
        tbl=self.tabs.currentWidget()
        if tbl not in self.patient_tables:
            QMessageBox.warning(self, "Aviso ⚠️", "Selecione uma aba de pacientes.")
            return
        if tbl is self.tbl_left: return
        rows=tbl.selectionModel().selectedRows()
        if not rows: QMessageBox.warning(self,"Aviso ⚠️","Selecione o paciente."); return
        dlg=SimpleTimeDialog("Horário de Saída ⏲️",self)
        if not dlg.exec_(): return
        left_inf=dlg.hour(); left_sys=QTime.currentTime().toString("HH:mm")
        for r in rows:
            pid=int(tbl.item(r.row(),0).text())
            try:
                leave_record(pid,left_sys,left_inf)
            except ValueError as exc:
                QMessageBox.warning(self, "Aviso ⚠️", str(exc))
            except Exception as exc:
                QMessageBox.critical(self, "Erro ❌", str(exc))
        self.refresh()

    # -------- reativar
    def activate(self):
        if self.tabs.currentWidget() is not self.tbl_left:
            QMessageBox.warning(self,"Aviso ⚠️","Vá para aba Saíram."); return
        rows=self.tbl_left.selectionModel().selectedRows()
        if not rows: QMessageBox.warning(self,"Aviso ⚠️","Selecione o paciente."); return
        dlg=SimpleTimeDialog("Horário de Retorno ⏰",self)
        if not dlg.exec_(): return
        enter_inf=dlg.hour(); enter_sys=QTime.currentTime().toString("HH:mm")
        for r in rows:
            pid=int(self.tbl_left.item(r.row(),0).text())
            try: reactivate_from(pid,enter_sys,enter_inf)
            except Exception as e: QMessageBox.critical(self,"Erro ❌",str(e))
        self.refresh()

    # -------- editar refeições
    def edit_meals(self):
        tbl = self.tabs.currentWidget()
        rows = tbl.selectionModel().selectedRows()
        if not rows:
            QMessageBox.warning(self,"Aviso ⚠️","Selecione o paciente."); return

        pid = int(tbl.item(rows[0].row(), 0).text())

        with get_conn() as c:
            row = c.execute(
                "SELECT desjejum,lunch,snack,dinner FROM records WHERE id=?",
                (pid,)
            ).fetchone()

        if row is None:
            raise RuntimeError("ID não encontrado.")

        b,l,s,d = row

        dlg = QDialog(self); dlg.setWindowTitle("Editar Refeições 🍽️")
        lay = QFormLayout(dlg)
        cb_b = QCheckBox("Desjejum 🥞"); cb_b.setChecked(bool(b))
        cb_l = QCheckBox("Almoço 🥗");   cb_l.setChecked(bool(l))
        cb_s = QCheckBox("Lanche 🥪");   cb_s.setChecked(bool(s))
        cb_d = QCheckBox("Janta 🍛");    cb_d.setChecked(bool(d))
        for cb in (cb_b, cb_l, cb_s, cb_d): lay.addRow(cb)
        lay.addRow("", QPushButton("Salvar ✅", clicked=dlg.accept))

        if not dlg.exec_():
            return

        try:
            update_meals(
                pid,
                int(cb_b.isChecked()), int(cb_l.isChecked()),
                int(cb_s.isChecked()), int(cb_d.isChecked())
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, "Erro ❌", str(exc))


    # ------------------------------------------------------------
    #  EDITAR REGISTRO (nome, prof., obs, demandas, refeições)
    # ------------------------------------------------------------
    def edit_record(self):
        tbl = self.tabs.currentWidget()
        sel = tbl.selectionModel().selectedRows()
        if not sel:
            QMessageBox.warning(self, "Aviso ⚠️", "Selecione o paciente antes.")
            return

        pid = int(tbl.item(sel[0].row(), 0).text())

        # --------------- carrega dados atuais ---------------
        with get_conn() as c:
            row = c.execute("""
                SELECT patient_name, demands, reference_prof, observations,
                       start_time, end_time, encaminhamento,
                       desjejum, lunch, snack, dinner
                FROM records WHERE id=?""", (pid,)
            ).fetchone()

        if row is None:
            raise RuntimeError("ID não encontrado.")

        (name, demands, prof, obs,
         start_t, end_t, enc,
         b, l, s, d) = row

        tokens_atual = {tok.strip().split(" ")[0]
                        for tok in (demands or "").split(",") if tok}

        # --------------- monta diálogo ---------------
        dlg = QDialog(self); dlg.setWindowTitle("Editar registro 📝")
        lay = QFormLayout(dlg)

        txt_nome = QLineEdit(name)
        txt_prof = QLineEdit(prof)
        txt_obs  = QLineEdit(obs or "")

        lay.addRow("Paciente:",            txt_nome)
        lay.addRow("Profissional ref.:",   txt_prof)
        lay.addRow("Observações:",         txt_obs)

        # ----- check-boxes de demanda ----------------------------------------
        chk_map: dict[str, QCheckBox] = {}
        for d in DEMAND_LIST:
            box = QCheckBox(d)
            box.setChecked(d in tokens_atual)
            chk_map[d] = box
            lay.addRow(box)

        lbl_int = QLabel()                     # mostra intervalo atual, se houver
        if start_t and end_t:
            lbl_int.setText(f"Intervalo atual: {start_t}-{end_t}")
        lay.addRow(lbl_int)

        # ------------------------------------------------------------------
        # helper: liga/desliga sem disparar sinais recursivos
        def _mute(box: QCheckBox, value: bool) -> None:
            box.blockSignals(True)
            box.setChecked(value)
            box.blockSignals(False)

        # ------------------------------------------------------------------
        # 1) AI / REA exclusivos
        def _enforce_ai_rule(state: int, box: QCheckBox) -> None:
            nonlocal enc
            ai_codes = ("AI", "REA")
            ai_on    = any(chk_map[c].isChecked() for c in ai_codes)
            other_on = any(
                chk_map[c].isChecked() for c in DEMAND_LIST if c not in ai_codes
            )

            if ai_on and other_on:
                if box.text() in ai_codes:                 # clique foi em AI/REA
                    for c in (d for d in DEMAND_LIST if d not in ai_codes):
                        _mute(chk_map[c], False)
                else:                                      # clique foi em outra demanda
                    for c in ai_codes:
                        _mute(chk_map[c], False)
                    enc = None                             # perdeu o encaminhamento

        # ------------------------------------------------------------------
        # 2) Exclusividade R / M / RM
        def _rm_logic(_: int) -> None:
            trio = ("R", "M", "RM")
            if sum(chk_map[c].isChecked() for c in trio) >= 2:
                QMessageBox.information(
                    dlg, "Demanda duplicada",
                    "Para registrar R + M use apenas a opção **RM**."
                )
                for c in trio:
                    _mute(chk_map[c], c == "RM")           # só RM fica ligado

        # ------------------------------------------------------------------
        # 3) Convívio – pede intervalo
        def _ask_interval(state: int) -> None:
            nonlocal start_t, end_t
            if state == Qt.Checked:
                d = TimeIntervalDialog(dlg)
                if d.exec_():                              # usuário escolheu
                    start_t, end_t = d.interval()
                    lbl_int.setText(f"Intervalo: {start_t}-{end_t}")
                else:                                      # cancelou → desmarca C
                    _mute(chk_map["C"], False)
                    start_t = end_t = None
                    lbl_int.clear()
            else:                                          # C foi desmarcado
                start_t = end_t = None
                lbl_int.clear()

        # ------------------------------------------------------------------
        # liga sinais
        for cb in chk_map.values():                        # AI/REA sempre checados
            cb.stateChanged.connect(lambda st, b=cb: _enforce_ai_rule(st, b))

        for cod in ("R", "M", "RM"):                       # R + M → RM
            chk_map[cod].stateChanged.connect(_rm_logic)

        chk_map["C"].stateChanged.connect(_ask_interval)   # Convívio

        # ------------------------------------------------------------------
        # AI/REA ⇒ diálogo de encaminhamento (só se ligados)
        def _ask_enc(state: int) -> None:
            nonlocal enc
            if state == Qt.Checked:
                d = EncaminhamentoDialog(dlg)
                if d.exec_():
                    enc = d.choice()
                else:                                      # cancelou ⇒ desmarca AI/REA
                    for c in ("AI", "REA"):
                        _mute(chk_map[c], False)
                    enc = None
            else:
                enc = None

        for c in ("AI", "REA"):
            chk_map[c].stateChanged.connect(_ask_enc)


        lay.addRow("", QPushButton("Salvar ✅", clicked=dlg.accept))

        # --------------- cancelou ---------------
        if dlg.exec_() == 0:
            return

        # --------------- coleta alterações ---------------
        new_name = txt_nome.text().strip()
        new_prof = txt_prof.text().strip()
        new_obs  = txt_obs.text().strip()

        if not new_name or not new_prof:
            QMessageBox.warning(self, "Faltando dados",
                                "Nome do paciente e Profissional são obrigatórios.")
            return

        sel_tokens = [d for d, ck in chk_map.items() if ck.isChecked()]
        if not sel_tokens:
            QMessageBox.warning(self, "Faltando demanda", "Marque pelo menos uma demanda.")
            return

        def fmt_C():                                      # Convívio formatado
            return f"C ({start_t}-{end_t})" if start_t and end_t else "C"
        new_demands = ", ".join(fmt_C() if d == "C" else d for d in sel_tokens)

        # ---------- refeições automáticas se Convívio ----------
        if "C" in sel_tokens and start_t and end_t:
            def covers(qt):
                t0 = QTime.fromString(start_t, "HH:mm")
                t1 = QTime.fromString(end_t, "HH:mm")
                return t0 <= qt <= t1
            new_b = int(covers(HORARIOS["desjejum"]))
            new_l = int(covers(HORARIOS["almoco"]))
            new_s = int(covers(HORARIOS["lanche"]))
            new_d = int(covers(HORARIOS["janta"]))
            update_meals(pid, new_b, new_l, new_s, new_d)
            ask_meals = False
        else:
            ask_meals = QMessageBox.question(
                self, "Refeições",
                "Deseja alterar refeições conforme nova demanda?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) == QMessageBox.Yes

        # ---------- grava tudo ----------
        try:
            update_demands(pid, new_demands, start_t, end_t, enc)

            with get_conn() as c:
                c.execute("""
                    UPDATE records SET patient_name=?, reference_prof=?, observations=?
                    WHERE id=?""", (new_name, new_prof, new_obs, pid))
                c.commit()

            if ask_meals:
                self.refresh()
                # re-seleciona para abrir o diálogo correto
                for r in range(tbl.rowCount()):
                    if int(tbl.item(r, 0).text()) == pid:
                        tbl.selectRow(r)
                        break
                self.edit_meals()

            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, "Erro ❌", str(exc))

    # ------------------------------------------------------------
    #  OBSERVAÇÕES DO DIA
    # ------------------------------------------------------------
    def _show_observations(self):
        iso = self.date.date().toString("dd/MM/yyyy")
        with get_conn() as c:
            rows = c.execute("""
                SELECT id, patient_name, observations
                FROM records
                WHERE date=? AND observations IS NOT NULL
                      AND TRIM(observations) <> ''
            """, (iso,)).fetchall()

        if not rows:
            QMessageBox.information(self, "Observações",
                                    "Nenhum paciente com observação no dia.")
            return

        dlg = QDialog(self); dlg.setWindowTitle(f"Observações – {len(rows)} pacientes")
        tbl = QTableWidget(len(rows), 2, dlg)
        tbl.setHorizontalHeaderLabels(["Paciente", "Observação"])
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        for r, (_, nome, obs) in enumerate(rows):
            tbl.setItem(r, 0, QTableWidgetItem(nome))
            tbl.setItem(r, 1, QTableWidgetItem(obs))

        def show_obs(item):
            linha = item.row()
            QMessageBox.information(
                dlg, rows[linha][1],
                rows[linha][2]
            )

        tbl.itemDoubleClicked.connect(show_obs)

        lay = QVBoxLayout(dlg); lay.addWidget(tbl)
        dlg.resize(600, 400); dlg.exec_()



    # -------- histórico (duplo clique)
    def show_history(self, item):
        pid = int(item.tableWidget().item(item.row(), 0).text())
        with get_conn() as c:
            meal = c.execute(
                "SELECT ts,old_b,old_l,old_s,old_d,new_b,new_l,new_s,new_d "
                "FROM meal_log WHERE record_id=? ORDER BY log_id",
                (pid,)).fetchall()
            dem  = c.execute(
                "SELECT ts,old_demands,new_demands "
                "FROM demand_log WHERE record_id=? ORDER BY log_id",
                (pid,)).fetchall()

        if not meal and not dem:
            QMessageBox.information(self, "Histórico", "Sem alterações registradas.")
            return

        def flag(b,l,s,d):
            return ", ".join([n for n,v in zip(
                ["🥞 Desjejum", "🥗 Almoço", "🥪 Lanche", "🍛 Janta"],
                [b,l,s,d]) if v]) or "—"

        txt = "📜 Histórico:\n\n"
        for ts,ob,ol,os,od,nb,nl,ns,nd in meal:
            txt += f"{ts}: {flag(ob,ol,os,od)}  ➜  {flag(nb,nl,ns,nd)}\n"
        for ts,od,nd in dem:
            txt += f"{ts}: Demandas '{od or '—'}'  ➜  '{nd}'\n"

        QMessageBox.information(self, "Histórico ✏️", txt)


    # ───────────────────────────────────────── refresh COMPLETO ─────────────────────────────────────────
    def refresh(self):
        iso = self.date.date().toString("dd/MM/yyyy")
                # traz AN / AN Entrou do dia anterior
        self._rollover_an(iso)
                # garante que o combo está sempre sincronizado
        self._update_demand_filter_combo()



        # ——— puxa dados do BD ———
        with get_conn() as c:
            today_rows = c.execute(
                "SELECT * FROM records WHERE date=? AND left_sys IS NULL",
                (iso,),
            ).fetchall()
            all_rows   = c.execute("SELECT * FROM records").fetchall()

        day = self._metrics(today_rows)
        tot = self._metrics(all_rows)
        counts_today = counts(iso)

        # --- mini-contadores do dashboard ---
        mini = {
            "desj":  day["desj"],
            "lunch": day["alm"],
            "snack": day["lan"],
            "dinner":day["jan"],
            "total": counts_today["total de Pacientes"],
            "acolh": counts_today["acolh"],
        }
        for k, v in mini.items():
            lbl = self.dash_lbls.get(k)        # ← evita KeyError se faltar
            if lbl is not None:
                lbl.setText(str(v))

        # --- preenche tabelas principais ---
        self._fill(self.tbl_all,   self.fetch(iso, "AND left_sys IS NULL"))
        self._fill(self.tbl_break, self.fetch(iso, "AND desjejum=1 AND left_sys IS NULL"))
        self._fill(self.tbl_lunch, self.fetch(iso, "AND lunch=1 AND left_sys IS NULL"))
        self._fill(self.tbl_snack, self.fetch(iso, "AND snack=1 AND left_sys IS NULL"))
        self._fill(self.tbl_dinner,self.fetch(iso, "AND dinner=1 AND left_sys IS NULL"))
        self._fill(
            self.tbl_acolh,
            self._fetch_acolh(iso),
            include_enc=True
        )
        self._fill(self.tbl_left,  self.fetch(iso, "AND left_sys IS NOT NULL"))

        # --- consolidados ---
        self._fill_cons(self.tbl_cons_day,   day)
        self._fill_cons(self.tbl_cons_total, tot)


    # ------------------------------------------------------------
    #  Atualiza a lista do combo de filtro de demandas (painel principal)
    # ------------------------------------------------------------
    def _update_demand_filter_combo(self):
        """Preenche cmb_dmd_filter apenas com *códigos visíveis* no dia atual.

        • C (…intervalo…)             → aparece como  C  
        • AN / AN Entrou / AN Saiu    → cada um aparece separado  
        • AI / REA / A / R / M / RM … → idem
        """
        if not hasattr(self, "cmb_dmd_filter"):   # chamado antes da criação?
            return

        iso  = self.date.date().toString("dd/MM/yyyy")
        seen = set()

        with get_conn() as c:
            for (demands,) in c.execute(
                "SELECT DISTINCT demands FROM records "
                "WHERE date=? AND demands IS NOT NULL", (iso,)
            ):
                for tok in (demands or "").split(","):
                    tok = tok.strip()
                    if not tok:
                        continue

                    # -------- regras de extração -----------------
                    if tok.startswith("C"):
                        key = "C"                         # C (10:00-12:00) → C
                    elif tok.startswith("AN Entrou"):
                        key = "AN Entrou"
                    elif tok.startswith("AN Saiu"):
                        key = "AN Saiu"
                    else:
                        key = tok.split(" ")[0]           # A, R, RM, AI, REA…
                    seen.add(key)

        # guarda seleção atual
        old_sel = self.cmb_dmd_filter.currentData()

        self.cmb_dmd_filter.blockSignals(True)
        self.cmb_dmd_filter.clear()
        self.cmb_dmd_filter.addItem("— Todas as demandas —", "")

        for code in sorted(seen):
            self.cmb_dmd_filter.addItem(code, code)

        # restaura seleção, se ainda existir
        i = self.cmb_dmd_filter.findData(old_sel)
        self.cmb_dmd_filter.setCurrentIndex(i if i != -1 else 0)
        self.cmb_dmd_filter.blockSignals(False)




    def _clear(self):
        self.txt_name.clear(); self.txt_ref.clear(); self.txt_obs.clear()
        self.lbl_conv.setText(""); self.lbl_enc.setText("")
        self.start_time=self.end_time=self.enc=None
        for cb in self.dem_cb: cb.setChecked(False)
        for chk in (self.chk_b,self.chk_l,self.chk_s,self.chk_d): chk.setChecked(False)
        

# ───────────────────────────────────────────────────────────── run
if __name__=="__main__":
    app=QApplication(sys.argv); w=Main(); w.show(); sys.exit(app.exec_())

    
