from pydantic import SecretStr

from docstate.settings import Settings


def test_database_url_from_components():
    s = Settings(
        db_host="db.internal",
        db_port=5001,
        db_user="app",
        db_password=SecretStr("p@ss/w"),
        db_name="docs",
    )
    assert s.database_url == "postgresql+psycopg://app:p%40ss%2Fw@db.internal:5001/docs"
    assert not s.is_sqlite


def test_bare_postgres_and_mysql_urls_get_their_drivers():
    assert Settings(storage_url="postgres://u:p@h/d").database_url == "postgresql+psycopg://u:p@h/d"
    assert (
        Settings(storage_url="postgresql://u:p@h/d").database_url == "postgresql+psycopg://u:p@h/d"
    )
    assert Settings(storage_url="mysql://u:p@h/d").database_url == "mysql+pymysql://u:p@h/d"
    assert (
        Settings(storage_url="postgresql+psycopg://u:p@h/d").database_url
        == "postgresql+psycopg://u:p@h/d"
    )


def test_sqlite_stays_sqlite():
    s = Settings(storage_url="sqlite:////tmp/x.db", db_schema="docs")
    assert s.is_sqlite and s.database_url == "sqlite:////tmp/x.db"


def test_named_api_tokens():
    s = Settings(api_tokens="ci:abc, agent:def,bare")
    assert s.api_token_map == {"abc": "ci", "def": "agent", "bare": "api"}
    assert Settings(api_tokens="").api_token_map == {}


def test_toml_file_and_profile(tmp_path, monkeypatch):
    cfg = tmp_path / "docstate.toml"
    cfg.write_text(
        'site_title = "Team docs"\nlang = "en"\n\n[profiles.prod]\nlang = "zh-CN"\nlogin_url = "https://sso.example.com"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCSTATE_CONFIG", str(cfg))
    monkeypatch.delenv("DOCSTATE_PROFILE", raising=False)
    s = Settings()
    assert s.site_title == "Team docs" and s.lang == "en" and s.login_url == ""
    monkeypatch.setenv("DOCSTATE_PROFILE", "prod")
    s = Settings()
    assert s.lang == "zh-CN" and s.login_url == "https://sso.example.com"
    # the environment still wins over the file
    monkeypatch.setenv("DOCSTATE_LANG", "en")
    assert Settings().lang == "en"


def test_table_prefix_is_applied_to_names():
    from docstate.storage.sql.models import build_models

    m = build_models("team_", None)
    assert m.Doc.__tablename__ == "team_docs" and m.table("doc_state") == "team_doc_state"
    assert build_models("", None).Doc.__tablename__ == "docs"
