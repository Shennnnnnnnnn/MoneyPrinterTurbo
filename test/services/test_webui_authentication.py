import os
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app import auth


WEBUI_MAIN = Path(__file__).parents[2] / "webui" / "Main.py"


def _widget_by_key(widgets, key):
    return next(widget for widget in widgets if widget.key == key)


def test_webui_requires_admin_login_before_rendering_application():
    with patch.dict(os.environ, {auth.ADMIN_PASSWORD_ENV_VAR: "test-password"}):
        app = AppTest.from_file(str(WEBUI_MAIN), default_timeout=30)
        app.session_state["ui_language"] = "en"
        app.run()

        assert _widget_by_key(app.text_input, "webui_login_username")
        password_input = _widget_by_key(app.text_input, "webui_login_password")
        assert password_input.proto.type == password_input.proto.PASSWORD
        assert not any(button.key == "generate_video_button" for button in app.button)

        _widget_by_key(app.text_input, "webui_login_username").set_value("admin").run()
        password_input.set_value("test-password").run()
        _widget_by_key(app.button, "webui_login_submit").click().run()

        assert app.session_state["webui_authenticated"] is True
        assert any(button.key == "generate_video_button" for button in app.button)
