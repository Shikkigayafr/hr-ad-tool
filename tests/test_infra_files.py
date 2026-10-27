"""Инфраструктурные файлы (infra/) должны быть согласованы с кодом панели."""
import glob
import json
import os

import ad_utils
from hrpanel.services import DEPARTMENTS, EMPLOYEE_ROLES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_structure():
    with open(os.path.join(ROOT, "infra", "ad", "structure.json"), encoding="utf-8") as f:
        return json.load(f)


def test_structure_departments_match_application():
    structure = load_structure()
    assert structure["departments"] == DEPARTMENTS, "OU отделов в infra/ad/structure.json разошлись с saby_config.py"


def test_structure_groups_match_roles():
    assert load_structure()["groups"] == list(EMPLOYEE_ROLES)


def test_ou_names_match_ad_utils_defaults():
    ous = load_structure()["ous"]
    # ad_utils создаёт пользователей в OU=<отдел>,OU=Departments — имя OU зашито в коде
    with open(os.path.join(ROOT, "ad_utils.py"), encoding="utf-8") as f:
        source = f.read()
    assert f"OU={ous['departments']}," in source
    assert ad_utils.GROUPS_OU.startswith(f"OU={ous['groups']},")
    assert ad_utils.DISABLED_OU.startswith(f"OU={ous['disabled']},")


def test_software_list_is_valid():
    with open(os.path.join(ROOT, "infra", "deploy", "software.json"), encoding="utf-8") as f:
        items = json.load(f)
    assert items
    for item in items:
        assert item["type"] in ("winget", "msi", "exe"), item
        if item["type"] == "winget":
            assert item["id"], item
        else:
            assert item["path"] and item["detect"], item   # без detect скрипт не знал бы, что уже установлено


def test_powershell_scripts_have_utf8_bom():
    """Windows PowerShell 5.1 читает .ps1 без BOM как ANSI и портит кириллицу."""
    scripts = glob.glob(os.path.join(ROOT, "infra", "**", "*.ps1"), recursive=True)
    assert len(scripts) >= 6
    without_bom = [os.path.relpath(p, ROOT) for p in scripts if not open(p, "rb").read(3) == b"\xef\xbb\xbf"]
    assert not without_bom, f"Нет UTF-8 BOM: {without_bom}"


def test_bat_files_are_ascii_only():
    for path in glob.glob(os.path.join(ROOT, "infra", "**", "*.bat"), recursive=True):
        with open(path, "rb") as f:
            f.read().decode("ascii")   # кириллица в .bat зависит от кодовой страницы консоли


def test_no_continue_inside_switch_in_deploy_script():
    """continue внутри switch не выходит из цикла foreach (была реальная ошибка в Install-Software.ps1)."""
    with open(os.path.join(ROOT, "infra", "deploy", "Install-Software.ps1"), encoding="utf-8") as f:
        source = f.read()
    switch_block = source.split("switch ($item.type)")[1].split("default {")[0]   # ветки winget / msi / exe
    assert "continue" not in switch_block
    assert source.count("break }") >= 3   # «уже установлено» и DryRun выходят из switch через break
