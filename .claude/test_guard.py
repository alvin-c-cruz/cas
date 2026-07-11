import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("guard", os.path.join(_HERE, "guard.py"))
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def test_ui_touching_flags_templates():
    files = ["app/sales_invoices/templates/list.html", "app/templates/base.html"]
    assert set(guard.ui_touching(files)) == set(files)


def test_ui_touching_flags_js_css_and_views():
    files = ["app/static/js/cas-ui.js", "app/static/css/style.css", "app/accounts/views.py"]
    assert set(guard.ui_touching(files)) == set(files)


def test_ui_touching_ignores_pure_backend():
    files = ["app/accounts/models.py", "tests/unit/test_x.py", "config.py", "app/utils/authz.py"]
    assert guard.ui_touching(files) == []


def test_ui_touching_empty_input():
    assert guard.ui_touching([]) == []
