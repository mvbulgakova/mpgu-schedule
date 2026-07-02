"""Тесты AI-ответа (заземление + обработка ошибок), без реального вызова API.

Запуск: python -m pytest scraper/tests/test_abitur_llm.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.abitur import llm


class _FakeBlock:
    type = "text"
    def __init__(self, text): self.text = text


class _FakeResp:
    def __init__(self, text): self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, captured): self._captured = captured
    def create(self, **kwargs):
        self._captured.update(kwargs)
        return _FakeResp("Справка 086/у нужна до 25 июля. https://mpgu.su/postuplenie/")


class _FakeClient:
    def __init__(self, captured): self.messages = _FakeMessages(captured)


def test_answer_grounds_on_kb_and_uses_haiku():
    captured = {}
    out = llm.answer("нужна ли справка?", client=_FakeClient(captured))
    assert "086" in out
    assert captured["model"] == "claude-haiku-4-5"
    # система содержит базу знаний и anti-hallucination инструкции
    system = captured["system"]
    sys_text = system if isinstance(system, str) else system[0]["text"]
    assert "priem@mpgu.su" in sys_text
    assert "не выдум" in sys_text.lower() or "только" in sys_text.lower()


def test_answer_sets_cache_control_on_system():
    captured = {}
    llm.answer("вопрос", client=_FakeClient(captured))
    system = captured["system"]
    assert isinstance(system, list)
    assert system[-1].get("cache_control", {}).get("type") == "ephemeral"


def test_answer_error_falls_back_to_contacts():
    class _Boom:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("api down")
    out = llm.answer("вопрос", client=_Boom())
    assert "priem@mpgu.su" in out


def test_answer_without_client_factory_failure_is_graceful():
    # эмулируем отсутствие кредов: фабрика клиента бросает
    def _raise():
        raise ValueError("нет ключа")
    out = llm.answer("вопрос", client=None, client_factory=_raise)
    assert "priem@mpgu.su" in out
