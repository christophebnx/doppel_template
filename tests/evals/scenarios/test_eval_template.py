"""Template scenarios: the template names no mail/calendar account and no base; a project starts with collection off
and can only enable it once declared private; the template itself never upgrades from itself."""
import collect
import common
import setup
import template


def test_template_ships_without_accounts(doppel_root):
    root = doppel_root("2026-11-24 08:00")
    cfg = common.load_config(root)
    assert cfg["collect"]["calendars"] == [] and cfg["collect"]["enabled"] is False
    assert not cfg["template"]["base"] and cfg["template"]["repo"]
    assert collect.guard(root)[0] is False


def test_project_enables_its_own_accounts_only_when_private(doppel_root):
    root = doppel_root("2026-11-24 08:00")
    try:
        setup.set_collect(root, enable=True, calendars=["agenda@exemple.be=famille"])
        raise AssertionError("enabled without --private")
    except SystemExit:
        pass
    setup.set_collect(root, enable=True, private=True, calendars=["agenda@exemple.be=famille"])
    assert collect.guard(root)[0] and collect.plan(root)["calendars"][0]["alias"] == "famille"
    try:
        template.upgrade(root)
        raise AssertionError("upgrade without base")
    except SystemExit as e:
        assert "base" in str(e) or "git" in str(e)
