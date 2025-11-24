import sqlite3

import pytest

pytest.importorskip("PyQt5")

import registro_pac


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "patients.db"
    monkeypatch.setattr(registro_pac, "DB_PATH", db_file)
    registro_pac.init_db()
    return db_file


@pytest.fixture
def sample_record(temp_db):
    registro_pac.add_record(
        {
            "patient_name": "Paciente",
            "demands": "AI, C",
            "reference_prof": "Prof",
            "date": "2024-01-01",
            "enter_sys": "08:00",
            "enter_inf": "08:00",
            "left_sys": None,
            "left_inf": None,
            "observations": "",
            "encaminhamento": None,
            "desjejum": 0,
            "lunch": 0,
            "snack": 0,
            "dinner": 0,
            "start_time": "09:00",
            "end_time": "10:00",
            "archived_ai": 0,
        }
    )
    with sqlite3.connect(temp_db) as c:
        return c.execute("SELECT id FROM records").fetchone()[0]


def test_init_db_creates_tables_and_columns(temp_db):
    with sqlite3.connect(temp_db) as c:
        tables = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"records", "meal_log", "demand_log"}.issubset(tables)

        columns = {row[1] for row in c.execute("PRAGMA table_info(records)")}
        for col in ["enter_sys", "enter_inf", "left_sys", "left_inf", "desjejum", "archived_ai"]:
            assert col in columns


def test_update_meals_logs_changes(temp_db, sample_record):
    pid = sample_record
    registro_pac.update_meals(pid, 1, 0, 1, 0)

    with sqlite3.connect(temp_db) as c:
        meals = c.execute(
            "SELECT desjejum,lunch,snack,dinner FROM records WHERE id=?", (pid,)
        ).fetchone()
        assert meals == (1, 0, 1, 0)

        log_rows = c.execute("SELECT old_b,old_l,old_s,old_d,new_b,new_l,new_s,new_d FROM meal_log").fetchall()
        assert log_rows == [(0, 0, 0, 0, 1, 0, 1, 0)]

    # calling again with same values should not create a duplicate log
    registro_pac.update_meals(pid, 1, 0, 1, 0)
    with sqlite3.connect(temp_db) as c:
        assert c.execute("SELECT COUNT(*) FROM meal_log").fetchone()[0] == 1


def test_update_demands_clones_ai_and_logs(monkeypatch, temp_db, sample_record):
    pid = sample_record
    monkeypatch.setattr(
        registro_pac.QTime,
        "currentTime",
        staticmethod(lambda: registro_pac.QTime.fromString("10:00", "HH:mm")),
    )

    registro_pac.update_demands(pid, "C", new_start="11:00", new_end="12:00", new_enc="Enc")

    with sqlite3.connect(temp_db) as c:
        updated = c.execute(
            "SELECT demands,start_time,end_time,encaminhamento FROM records WHERE id=?",
            (pid,),
        ).fetchone()
        assert updated == ("C", "11:00", "12:00", "Enc")

        clones = c.execute(
            "SELECT demands,enter_inf,desjejum,lunch,snack,dinner,archived_ai FROM records WHERE archived_ai=1",
        ).fetchall()
        assert clones == [("AI", "10:00", 0, 0, 0, 0, 1)]

        log_rows = c.execute(
            "SELECT old_demands,new_demands FROM demand_log WHERE record_id=?", (pid,)
        ).fetchall()
        assert log_rows == [("AI, C", "C")]


def test_update_demands_requires_start_end_pair(temp_db, sample_record):
    with pytest.raises(ValueError):
        registro_pac.update_demands(sample_record, "C", new_start="10:00")

    with pytest.raises(ValueError):
        registro_pac.update_demands(sample_record, "C", new_end="11:00")


def test_update_demands_validates_time_format(temp_db, sample_record):
    with pytest.raises(ValueError):
        registro_pac.update_demands(sample_record, "C", new_start="25:00", new_end="26:00")


def test_fetch_acolh_ignores_archived_clones(monkeypatch, temp_db, sample_record):
    pid = sample_record

    with sqlite3.connect(temp_db) as c:
        c.execute(
            "UPDATE records SET encaminhamento=? WHERE id=?",
            ("EncOriginal", pid),
        )
        c.commit()

    monkeypatch.setattr(
        registro_pac.QTime,
        "currentTime",
        staticmethod(lambda: registro_pac.QTime.fromString("10:00", "HH:mm")),
    )

    registro_pac.update_demands(
        pid,
        "C",
        new_start="11:00",
        new_end="12:00",
        new_enc="EncAtualizada",
    )

    dummy = type("Dummy", (), {})()
    acolh = registro_pac.Main._fetch_acolh(dummy, "2024-01-01")

    assert [row[0] for row in acolh] == [pid]
    assert all(row[5] == 0 for row in acolh)


def test_leave_record_validates_time_and_updates(temp_db, sample_record):
    pid = sample_record

    with pytest.raises(ValueError):
        registro_pac.leave_record(pid, left_sys="07:00", left_inf="07:00")

    with sqlite3.connect(temp_db) as c:
        assert c.execute("SELECT left_sys,left_inf FROM records WHERE id=?", (pid,)).fetchone() == (None, None)

    registro_pac.leave_record(pid, left_sys="09:00", left_inf="09:00")
    with sqlite3.connect(temp_db) as c:
        assert c.execute("SELECT left_sys,left_inf FROM records WHERE id=?", (pid,)).fetchone() == (
            "09:00",
            "09:00",
        )

    with pytest.raises(ValueError):
        registro_pac.leave_record(pid, left_sys="10:00", left_inf="10:00")


def test_reactivate_from_updates_in_place(temp_db, sample_record):
    pid = sample_record

    registro_pac.update_meals(pid, 1, 1, 0, 0)
    registro_pac.leave_record(pid, left_sys="09:00", left_inf="09:00")

    with sqlite3.connect(temp_db) as c:
        c.execute("UPDATE records SET archived_ai=1 WHERE id=?", (pid,))
        c.commit()

    returned_id = registro_pac.reactivate_from(pid, enter_sys="10:00", enter_inf="10:00")

    with sqlite3.connect(temp_db) as c:
        record = c.execute(
            "SELECT id,enter_sys,enter_inf,left_sys,left_inf,archived_ai FROM records WHERE id=?",
            (pid,),
        ).fetchone()
        assert record == (pid, "10:00", "10:00", None, None, 0)

        assert c.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1

        meal_logs = c.execute("SELECT record_id FROM meal_log").fetchall()
        assert meal_logs == [(pid,)]

    assert returned_id == pid


def test_reactivate_from_validates_active_records(temp_db, sample_record):
    with pytest.raises(ValueError):
        registro_pac.reactivate_from(sample_record, enter_sys="08:30", enter_inf="08:30")


def test_counts_ignores_left_records(temp_db):
    registro_pac.add_record(
        {
            "patient_name": "Um",
            "demands": "A",
            "reference_prof": "Prof",
            "date": "2024-02-02",
            "enter_sys": "08:00",
            "enter_inf": "08:00",
            "left_sys": None,
            "left_inf": None,
            "observations": "",
            "encaminhamento": "Enc",
            "desjejum": 1,
            "lunch": 1,
            "snack": 0,
            "dinner": 1,
            "start_time": None,
            "end_time": None,
            "archived_ai": 0,
        }
    )
    registro_pac.add_record(
        {
            "patient_name": "Dois",
            "demands": "B",
            "reference_prof": "Prof",
            "date": "2024-02-02",
            "enter_sys": "09:00",
            "enter_inf": "09:00",
            "left_sys": "10:00",
            "left_inf": "10:00",
            "observations": "",
            "encaminhamento": None,
            "desjejum": 1,
            "lunch": 0,
            "snack": 1,
            "dinner": 0,
            "start_time": None,
            "end_time": None,
            "archived_ai": 0,
        }
    )

    assert registro_pac.counts("2024-02-02") == {
        "desj": 1,
        "lunch": 1,
        "snack": 0,
        "dinner": 1,
        "total de Pacientes": 1,
        "acolh": 1,
    }


def test_counts_ignores_archived_ai(temp_db):
    registro_pac.add_record(
        {
            "patient_name": "Ativo",
            "demands": "A",
            "reference_prof": "Prof",
            "date": "2024-03-03",
            "enter_sys": "08:00",
            "enter_inf": "08:00",
            "left_sys": None,
            "left_inf": None,
            "observations": "",
            "encaminhamento": None,
            "desjejum": 1,
            "lunch": 0,
            "snack": 0,
            "dinner": 0,
            "start_time": None,
            "end_time": None,
            "archived_ai": 0,
        }
    )
    registro_pac.add_record(
        {
            "patient_name": "Clone",
            "demands": "AI",
            "reference_prof": "Prof",
            "date": "2024-03-03",
            "enter_sys": "09:00",
            "enter_inf": "09:00",
            "left_sys": None,
            "left_inf": None,
            "observations": "",
            "encaminhamento": None,
            "desjejum": 0,
            "lunch": 0,
            "snack": 0,
            "dinner": 0,
            "start_time": None,
            "end_time": None,
            "archived_ai": 1,
        }
    )

    assert registro_pac.counts("2024-03-03") == {
        "desj": 1,
        "lunch": 0,
        "snack": 0,
        "dinner": 0,
        "total de Pacientes": 1,
        "acolh": 0,
    }
