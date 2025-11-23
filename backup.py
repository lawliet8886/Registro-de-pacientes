import json
import shutil
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
    """
    Garante um diretório de backup gravável dentro do Google Drive.
    Pergunta/ajusta até conseguir ou até o usuário cancelar.
    """
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
            # Falhou → explica e pede correção
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
