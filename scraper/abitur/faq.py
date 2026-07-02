"""FAQ: загрузка базы знаний, детерминированные темы-кнопки, маршрутизация текста."""
from pathlib import Path
from typing import Dict, Optional, Tuple

_KB_PATH = Path(__file__).with_name("knowledge.md")

# id -> (label кнопки, готовый ответ). Ответы детерминированы, без LLM.
TOPICS: Dict[str, Tuple[str, str]] = {
    "sroki": ("📅 Сроки", (
        "<b>Сроки приёма 2026:</b>\n"
        "• Документы (очно): 9 дней после объявления результатов ЕГЭ\n"
        "• Заочно: до 4 сентября\n"
        "• Зачисление по квотам/БВИ — 30 июля; основной этап — 8 августа\n"
        "• Справка 086/у (педагогические 44.xx) — до 25 июля\n"
        "• Договор и оплата на платном — до 27 августа\n\n"
        "Подробнее: https://mpgu.su/postuplenie/")),
    "documents": ("📄 Документы", (
        "<b>Подача документов:</b> онлайн https://mpgu.su/podat-dokumenty-onlajn/, "
        "через Госуслуги или лично. Перечень документов — на странице поступления "
        "https://mpgu.su/postuplenie/")),
    "vi": ("📝 ВИ и ДВИ", (
        "<b>Вступительные испытания:</b> обычный бакалавриат/БВО — по ЕГЭ. "
        "Внутренние ВИ вместо ЕГЭ — выпускникам колледжей/СПО, лицам с инвалидностью, "
        "иностранцам, лицам с ВО.\n"
        "<b>ДВИ</b> (творческие/проф.) — журналистика, физкультура, музыка, ИЗО, дизайн.\n"
        "Расписание: https://mpgu.su/raspisanie-vstupitelnyih-ispyitaniy/\n"
        "Программы: https://mpgu.su/postuplenie/entrance-test-programs/")),
    "levels": ("🎓 БВО / СПВО", (
        "<b>Уровни (пилот):</b> Базовое высшее образование (БВО) — основной уровень, "
        "4–6 лет, вместо бакалавриата/специалитета. Специализированное высшее (СПВО) и "
        "магистратура — углублённая подготовка, 1–3 года.\n"
        "Подробнее: https://mpgu.su/postuplenie/pilot/")),
    "bally": ("➕ Доп. баллы", (
        "<b>Индивидуальные достижения</b> дают до 10 баллов суммарно (на целевой квоте — до 15). "
        "Считаются один вид спорта (максимум), ГТО однократно; волонтёрство зависит от уровня и "
        "направления.\n"
        "Точный расчёт — команда /bally\n"
        "Перечень: https://mpgu.su/wp-content/uploads/2026/03/pk26_prilojenie-7-inye-meropriyatia.pdf")),
    "obshchezhitie": ("🏠 Общежитие", (
        "<b>Общежитие</b> предоставляется иногородним при регистрации свыше 70 км от МКАД. "
        "Подробности — https://mpgu.su/postuplenie/")),
    "celevoe": ("🎯 Целевое", (
        "<b>Целевое обучение:</b> заявка через «Работа России»/Госуслуги. Есть целевая квота; "
        "на ней повышенный потолок доп. баллов (до 15).\n"
        "Подробнее: https://mpgu.su/postuplenie/")),
    "lgoty": ("⭐ Льготы и квоты", (
        "<b>Особые права:</b> БВИ — победителям/призёрам олимпиад; квоты особая/целевая/отдельная "
        "(в т.ч. для участников СВО и их детей); преимущественное право.\n"
        "Подробнее: https://mpgu.su/postuplenie/")),
    "contacts": ("☎️ Контакты", (
        "<b>Приёмная комиссия МПГУ:</b>\n"
        "Email: priem@mpgu.su\n"
        "Тел.: +7 (499) 702-41-41, +7 (495) 438-18-47\n"
        "Адрес: пр-т Вернадского, 88, каб. 550\n"
        "Режим: Пн–Чт 10–17, Пт 10–16, Сб 10–14\n"
        "Договорный приём: dg@mpgu.su, +7 (495) 438-18-57")),
}


def load_knowledge() -> str:
    return _KB_PATH.read_text(encoding="utf-8")


def topic_answer(topic_id: str) -> Optional[str]:
    item = TOPICS.get(topic_id)
    return item[1] if item else None


def route(text: str) -> Tuple[str, str]:
    """Возвращает (intent, payload). intent: start|help|menu|calc|free."""
    t = (text or "").strip()
    cmd = t.split()[0].lower().split("@")[0] if t else ""
    if cmd in ("/start",):
        return ("start", "")
    if cmd in ("/help",):
        return ("help", "")
    if cmd in ("/abitur", "/menu", "/faq"):
        return ("menu", "")
    if cmd in ("/bally", "/ball", "/calc"):
        return ("calc", "")
    if cmd in ("/spisok", "/list", "/spiski"):
        arg = t[len(t.split()[0]):].strip() if t else ""
        return ("spisok", arg)
    return ("free", t)
