# Campeones

Draft an eleven from every European Cup quarter-finalist since 1994–95, one real
squad per turn, then take it through a 32-team tournament against the real thing.

```bash
uv sync
uv run uvicorn web.app:app --port 8030
```

- `SPEC.md`: the rules.
- `CLAUDE.md`: commands, measured figures and the decisions log.

Squads are read from Wikipedia (CC BY-SA). Ratings are this game's own judgement.
Real results for calibrating the match engine come from
[openfootball](https://github.com/openfootball/champions-league) (CC0). This is an
independent fan game, not affiliated with UEFA or any club.
