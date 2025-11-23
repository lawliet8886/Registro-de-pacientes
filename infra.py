import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt5.QtWidgets import QMessageBox, QInputDialog

DB_PATH = Path(__file__).with_name("patients.db")
CONFIG_FILE = Path(__file__).with_name("settings.json")


def _load_cfg() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_cfg(data: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_backup_root(parent=None) -> Optional[Path]:
    """Retorna um diretório de backup gravável dentro do Google Drive."""
    cfg = _load_cfg()
    root = Path(cfg.get("backup_root", r"G:\\Meu Drive\\backup_recepção"))
    parcial = r"G:\\Meu Drive"          # parte fixa (sem barra final)

    while True:
        try:
            root.mkdir(parents=True, exist_ok=True)
            tmp = root / "~write_test.tmp"
            tmp.write_text("ok")
            tmp.unlink()
            return root                          # 👍  tudo certo
        except Exception:
            msg = (
                "⚠️  Não consegui gravar o backup.\n\n"
                "• O Google Drive está instalado e logado como "
                "recepcaopauloportela@gmail.com?\n"
                "• No Explorador de Arquivos, existe o disco “Google Drive (G:)”?\n\n"
                "Agora informe (ou crie) a pasta onde os backups serão salvos.\n"
                f"O início já está preenchido:  {parcial}\\"
            )
            sugestao = (
                str(root).replace(parcial + "\\", "", 1)
                if str(root).startswith(parcial) else ""
            )
            pasta, ok = QInputDialog.getText(
                parent, "Corrigir pasta de backup", msg, text=sugestao
            )
            if not ok:               # usuário cancelou
                return None
            root = Path(parcial) / pasta.strip(" /\\")
            cfg["backup_root"] = str(root)
            _save_cfg(cfg)


def backup_now(parent=None) -> None:
    """
    Copia patients.db para:
        <pasta-backup>\\AAAA-MM\\<DD>\\patients_HH-MM-SS.db
    """
    root = get_backup_root(parent)
    if root is None:                              # usuário desistiu
        return

    try:
        now = datetime.now()
        month_dir = root / now.strftime("%Y-%m")
        day_dir = month_dir / now.strftime("%d")
        day_dir.mkdir(parents=True, exist_ok=True)

        dest = day_dir / f"patients_{now.strftime('%H-%M-%S')}.db"
        shutil.copy2(DB_PATH, dest)

        if parent:
            QMessageBox.information(
                parent, "Backup concluído ☁️",
                f"Arquivo salvo em:\n{dest}"
            )
    except Exception as exc:
        if parent:
            QMessageBox.critical(parent, "Falha no backup", str(exc))
        else:
            raise


def init_db():
    with sqlite3.connect(DB_PATH) as c:
        # tabela principal
        c.execute("""
        CREATE TABLE IF NOT EXISTS records(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          patient_name TEXT, demands TEXT, reference_prof TEXT,
          date TEXT,
          enter_sys TEXT, enter_inf TEXT,
          left_sys  TEXT, left_inf  TEXT,
          observations TEXT, encaminhamento TEXT,
          desjejum INTEGER DEFAULT 0, lunch INTEGER DEFAULT 0,
          snack INTEGER DEFAULT 0, dinner INTEGER DEFAULT 0,
          start_time TEXT, end_time TEXT
        )
        """)
        # tabela de log
        c.execute("""
        CREATE TABLE IF NOT EXISTS meal_log(
          log_id INTEGER PRIMARY KEY AUTOINCREMENT,
          record_id INTEGER, ts TEXT,
          old_b INTEGER, old_l INTEGER, old_s INTEGER, old_d INTEGER,
          new_b INTEGER, new_l INTEGER, new_s INTEGER, new_d INTEGER
        )
        """)

        # log de mudanças de demandas
        c.execute("""
        CREATE TABLE IF NOT EXISTS demand_log (
          log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
          record_id   INTEGER,
          ts          TEXT,
          old_demands TEXT,
          new_demands TEXT
        )
        """)

        # migração de colunas faltantes
        existing = [r[1] for r in c.execute("PRAGMA table_info(records)")]
        for col in ["enter_sys", "enter_inf", "left_sys", "left_inf", "desjejum"]:
            if col not in existing:
                c.execute(
                    f"ALTER TABLE records ADD COLUMN {col} "
                    f"{'INTEGER DEFAULT 0' if col=='desjejum' else 'TEXT'}"
                )
        # migra coluna 'time' antiga
        if "time" in existing and "enter_sys" in existing:
            c.execute("UPDATE records SET enter_sys=time WHERE enter_sys IS NULL OR enter_sys=''" )
        c.commit()
        if "archived_ai" not in existing:
            c.execute("ALTER TABLE records ADD COLUMN archived_ai INTEGER DEFAULT 0")


def _fix_old_imports(parent=None):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE records
               SET enter_sys = enter_inf
             WHERE enter_inf GLOB '??:??'
               AND (enter_sys IS NULL OR enter_sys <> enter_inf)
        """)
        n1 = cur.rowcount
        cur.execute("""
            UPDATE records
               SET desjejum = 1
             WHERE desjejum = 0
               AND enter_inf LIKE '09:%'
        """)
        n2 = cur.rowcount
        conn.commit()
    QMessageBox.information(parent, "Reparo concluído",
                            f"{n1} horários corrigidos\n{n2} desjejuns marcados")
