from bot.keyboards.institutes import build_institutes_kb
from bot.keyboards.groups import build_groups_kb
from bot.keyboards.schedule import build_schedule_kb


def test_institutes_kb_has_buttons():
    institutes = [
        {"id": "biology", "name": "Биология и химия"},
        {"id": "sport", "name": "Физкультура"},
    ]
    kb = build_institutes_kb(institutes)
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(buttons) == 2
    assert buttons[0].callback_data == "inst:biology"


def test_groups_kb_pagination():
    groups = [{"name": f"БИО{i:02d}-БА2501"} for i in range(25)]
    kb = build_groups_kb(groups, page=0, institute_id="bio")
    all_buttons = [btn for row in kb.inline_keyboard for btn in row]
    nav = [b for b in all_buttons if "→" in (b.text or "")]
    assert len(nav) == 1
    # Verify institute_id is encoded in the callback data
    assert nav[0].callback_data == "grp_page:bio:1"


def test_groups_kb_page_2():
    groups = [{"name": f"БИО{i:02d}-БА2501"} for i in range(25)]
    kb = build_groups_kb(groups, page=1, institute_id="bio")
    all_buttons = [btn for row in kb.inline_keyboard for btn in row]
    nav_prev = [b for b in all_buttons if "←" in (b.text or "")]
    assert len(nav_prev) == 1
    # Verify institute_id is encoded in the callback data
    assert nav_prev[0].callback_data == "grp_page:bio:0"


def test_schedule_kb_has_four_buttons():
    kb = build_schedule_kb("БИО40-БА2501")
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    texts = [b.text for b in buttons]
    assert any("Завтра" in t for t in texts)
    assert any("неделя" in t.lower() for t in texts)
    assert any("Ошибка" in t for t in texts)
