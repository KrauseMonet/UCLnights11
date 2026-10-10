"""The local .env loader: .env.local (what `neon deploy` writes) wins over .env, and a
variable already set wins over both."""

from web import env


def test_env_local_wins_and_the_environment_wins_over_both(tmp_path, monkeypatch):
    (tmp_path / ".env.local").write_text("# neon\nA='from_local'\nexport D=\"quoted\"\n")
    monkeypatch.setattr(env, "ROOT", tmp_path)
    for k in "ABCD":
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("C", "already")
    (tmp_path / ".env").write_text("A=from_env\nB=from_env\nC=from_env\n")
    env.load_dotenv()
    import os
    assert (os.environ["A"], os.environ["B"], os.environ["C"], os.environ["D"]) == \
        ("from_local", "from_env", "already", "quoted")
