import json

from wildlife_radar.cli import main


def test_demo_and_queries(tmp_path, capsys):
    db = str(tmp_path / "demo.duckdb")
    assert main(["demo", "--db", db]) == 0
    out = capsys.readouterr().out
    assert "backtest vernalis-litoralis" in out

    assert main(["query", "taxa", "--db", db]) == 0
    assert "raritas-orientalis" in capsys.readouterr().out

    args = ["query", "place", "--db", db, "--lat", "32.85", "--lon", "-117.27"]
    assert main([*args, "--date", "2026-05-15"]) == 0
    lists = json.loads(capsys.readouterr().out)
    assert lists["most_likely"] and lists["awareness"]

    assert main(["query", "species", "no-such", "--db", db]) == 1
    assert "not available" in capsys.readouterr().out

    assert main(["build-tiers", "--db", db, "--offline"]) == 0
    tiers = json.loads(capsys.readouterr().out.split("\nnote:")[0])
    assert tiers["tiers"] == {"COARSE": 3}  # offline: everything fails closed
