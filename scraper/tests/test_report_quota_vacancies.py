"""Тест CLI-отчёта по вакантным квотным местам (read-only).

Запуск: python -m pytest scraper/tests/test_report_quota_vacancies.py -v
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.report_quota_vacancies import main


def test_report_prints_vacancy_table(tmp_path, capsys):
    meta = {"lists": {
        "G": {"main_kcp": True, "direction": "44.03.01 Тест", "form": "очная",
              "unit": "ИФ", "kcp_epk": 33},
        "Q1": {"quota": True, "direction": "44.03.01 Тест", "form": "очная",
               "unit": "ИФ", "vid_mest": "отдельная квота",
               "kcp_epk": 9, "enrolled": 7},
    }}
    meta_path = tmp_path / "lists_meta.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    rc = main([str(meta_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "вакантно квот: 2" in out


def test_report_no_vacancies_message(tmp_path, capsys):
    meta_path = tmp_path / "lists_meta.json"
    meta_path.write_text(json.dumps({"lists": {}}), encoding="utf-8")

    rc = main([str(meta_path)])

    assert rc == 0
    assert "Незанятых квотных мест не найдено." in capsys.readouterr().out
