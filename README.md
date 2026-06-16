# battle-wrapper

Streamlined opening-repertoire pipeline:

**Play Games → Extract Middlegame → Analyze Critical Positions → Generate Repertoire Report**

## Usage

```bash
python3 main.py --1v1 stockfish viridithas --games 5 --depth 10 \
  --pgn openings/Nimzowich-Sicilian.pgn --analysis-depth 15
```

Output:
- Engine match PGN: `engine_battles/{Opening}-dd-mm_hh-mm-{games}-games.pgn`
- Repertoire report: `reports/{Opening}-Report-dd-mm_hh-mm.md`

## Notes

- No database and no intermediate legacy reports are generated.
- Middlegame analysis focuses on moves **15-35** only.
- Report includes game summary, pawn-structure snapshot, engine divergence, critical positions, and repertoire recommendation.
