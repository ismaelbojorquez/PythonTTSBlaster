import sys

import pytest

from blaster.config import Settings, load_settings


def test_explicit_trunks_do_not_inherit_the_unused_legacy_rtp_limit():
    # A small old [sip] range must not prevent raising capacity after moving to [[trunks]].
    data = {
        "concurrency": 15,
        "trunk_channels": 30,
        "sip": {"rtp_port_range": 20},
        "trunks": [
            {
                "id": "principal",
                "name": "Principal",
                "channels": 30,
                "sip": {"rtp_port": 18000, "rtp_port_range": 60},
            }
        ],
    }
    assert Settings.model_validate(data).concurrency == 15
    with pytest.raises(ValueError, match="RTP"):
        Settings.model_validate({**data, "trunks": []})
    data["trunks"][0]["sip"]["rtp_port_range"] = 20
    with pytest.raises(ValueError, match="RTP"):
        Settings.model_validate(data)


def test_sip_password_is_read_literally_from_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("BLASTER_SIP_PASSWORD", "must-not-be-used")
    path = tmp_path / "config.toml"
    path.write_text(
        'mode = "sip"\n'
        'voice_model = "voice.onnx"\n'
        "[sip]\n"
        'domain = "sip.example.test"\n'
        'username = "test"\n'
        "password = 'clave$á\\ruta\"final'\n",
        encoding="utf-8",
    )
    (tmp_path / "voice.onnx").touch()
    (tmp_path / "voice.onnx.json").touch()

    settings = load_settings(path)
    settings.validate_live()
    assert settings.sip.password == 'clave$á\\ruta"final'
    assert settings.sip.password not in repr(settings)
    assert "password" not in settings.model_dump()["sip"]

    with pytest.raises(ValueError) as error:
        Settings.model_validate(
            {"concurrency": 4, "trunk_channels": 6, "sip": {"password": settings.sip.password}}
        )
    assert settings.sip.password not in str(error.value)


def test_registration_requires_password_in_config_even_if_environment_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("BLASTER_SIP_PASSWORD", "must-not-be-used")
    voice = tmp_path / "voice.onnx"
    voice.touch()
    (tmp_path / "voice.onnx.json").touch()
    settings = Settings(voice_model=voice, sip={"domain": "sip.example.test", "username": "test"})
    with pytest.raises(ValueError, match=r"sip\.password en config\.toml"):
        settings.validate_live()

    settings.sip.registration_enabled = False
    settings.validate_live()


def test_server_uses_web_port_from_toml(tmp_path, monkeypatch):
    from blaster import __main__, web

    path = tmp_path / "config.toml"
    path.write_text("web_port = 9876\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["blaster", "--config", str(path)])
    app = object()
    monkeypatch.setattr(web, "create_app", lambda settings: app)
    started = []
    monkeypatch.setattr(
        __main__.uvicorn, "run", lambda app, **kwargs: started.append((app, kwargs))
    )

    __main__.main()
    assert started == [
        (
            app,
            {
                "host": "127.0.0.1",
                "port": 9876,
                "log_level": "info",
                "proxy_headers": True,
                "forwarded_allow_ips": "127.0.0.1,::1",
                "timeout_graceful_shutdown": 30,
            },
        )
    ]
