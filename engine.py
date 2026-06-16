import pathlib
import shutil
from typing import Dict, Optional

import chess
import chess.engine


class EngineAnalyzer:
    """Minimal UCI wrapper for evaluating a position."""

    def __init__(self, engine_path: str = "stockfish", depth: int = 15, threads: int = 1, hash_mb: int = 128):
        resolved = shutil.which(engine_path) or engine_path
        self.engine_path = pathlib.Path(resolved)
        self.depth = depth
        self.engine = chess.engine.SimpleEngine.popen_uci(str(self.engine_path))
        self.engine.configure({"Threads": threads, "Hash": hash_mb})

    def analyze(self, board: chess.Board) -> Dict[str, Optional[float]]:
        info = self.engine.analyse(board, chess.engine.Limit(depth=self.depth), multipv=1)
        if isinstance(info, list):
            info = info[0] if info else {}
        score = info["score"].white()
        cp = 1000.0 if score.is_mate() and score.mate() > 0 else -1000.0 if score.is_mate() else float(score.score() or 0) / 100.0
        pv = info.get("pv", [])
        return {"eval": cp, "best_move": pv[0].uci() if pv else None}

    def close(self) -> None:
        self.engine.quit()

    def __enter__(self) -> "EngineAnalyzer":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
