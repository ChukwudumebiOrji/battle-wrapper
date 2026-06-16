"""Focused opening repertoire analysis from engine battle PGN files."""

from __future__ import annotations

import datetime
import pathlib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional

import chess
import chess.pgn

from engine import EngineAnalyzer


@dataclass
class PositionSnapshot:
    game_index: int
    move_number: int
    san: str
    fen: str
    eval_before: Optional[float]
    eval_after: Optional[float]
    eval_shift: Optional[float]
    board_ascii: str


class RepertoireAnalyzer:
    MIDDLEGAME_START = 8
    MIDDLEGAME_END = 35

    def __init__(
        self,
        pgn_path: pathlib.Path,
        opening_name: str,
        analysis_depth: int = 15,
        engine_path: str = "stockfish",
    ):
        self.pgn_path = pathlib.Path(pgn_path)
        self.opening_name = opening_name.replace("_", "-").strip() or "Opening"
        self.analysis_depth = analysis_depth
        self.engine_path = engine_path

    def analyze_and_report(self, output_dir: pathlib.Path) -> pathlib.Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%d-%m_%H-%M")
        safe_opening = re.sub(r"[^A-Za-z0-9\- ]+", "", self.opening_name).strip().replace(" ", "-") or "Opening"
        report_path = output_dir / f"{safe_opening}-Report-{ts}.md"

        games = self._load_games()
        if not games:
            report_path.write_text(
                f"# {self.opening_name} - Engine Analysis Report\n\n"
                "No matching games were found for the requested opening.\n",
                encoding="utf-8",
            )
            return report_path

        with EngineAnalyzer(engine_path=self.engine_path, depth=self.analysis_depth) as analyzer:
            analyzed_games = [self._analyze_game(game, idx + 1, analyzer) for idx, game in enumerate(games)]

        report = self._build_report(analyzed_games, ts)
        report_path.write_text(report, encoding="utf-8")
        return report_path

    def _load_games(self) -> List[chess.pgn.Game]:
        if not self.pgn_path.exists():
            raise FileNotFoundError(f"PGN file not found: {self.pgn_path}")

        candidates: List[chess.pgn.Game] = []
        opening_target = self.opening_name.lower().replace("-", " ").strip()
        with self.pgn_path.open(encoding="utf-8") as handle:
            while True:
                game = chess.pgn.read_game(handle)
                if game is None:
                    break
                white = game.headers.get("White", "").lower()
                black = game.headers.get("Black", "").lower()
                if not self._is_engine_name(white) or not self._is_engine_name(black):
                    continue
                header_text = " ".join(
                    [game.headers.get("Opening", ""), game.headers.get("Variation", ""), game.headers.get("Event", "")]
                ).lower().replace("-", " ")
                if opening_target and opening_target not in header_text:
                    continue
                candidates.append(game)

        if candidates:
            return candidates

        # Fallback: if headers do not include opening name, keep all engine games from this PGN.
        with self.pgn_path.open(encoding="utf-8") as handle:
            while True:
                game = chess.pgn.read_game(handle)
                if game is None:
                    break
                if self._is_engine_name(game.headers.get("White", "").lower()) and self._is_engine_name(
                    game.headers.get("Black", "").lower()
                ):
                    candidates.append(game)
        return candidates

    @staticmethod
    def _is_engine_name(value: str) -> bool:
        return any(name in value for name in ("stockfish", "viridithas", "lc0", "komodo", "berserk"))

    @staticmethod
    def _parse_eval(comment: str) -> Optional[float]:
        if not comment:
            return None
        text = comment.strip().lower()
        if "book" in text:
            return None

        mate_match = re.search(r"#([+-]?\d+)", text)
        if mate_match:
            return 1000.0 if int(mate_match.group(1)) > 0 else -1000.0

        cp_match = re.search(r"([+-]?\d+(?:\.\d+)?)/\d+", text)
        if cp_match:
            try:
                return float(cp_match.group(1))
            except ValueError:
                return None
        return None

    def _analyze_game(self, game: chess.pgn.Game, index: int, analyzer: EngineAnalyzer) -> Dict:
        board = game.board()
        positions: List[PositionSnapshot] = []
        divergences: List[Dict] = []
        white, black = game.headers.get("White", "WHITE"), game.headers.get("Black", "BLACK")
        white_eval_at_move: Dict[int, float] = {}

        for ply, node in enumerate(game.mainline(), start=1):
            move = node.move
            move_num = (ply + 1) // 2
            if move_num > self.MIDDLEGAME_END:
                break

            san = board.san(move)
            eval_before = self._parse_eval(node.comment)
            board.push(move)

            if move_num < self.MIDDLEGAME_START:
                continue

            next_eval = self._parse_eval(node.variations[0].comment) if node.variations else None
            eval_shift = None
            if eval_before is not None and next_eval is not None:
                eval_shift = round(next_eval - eval_before, 2)

            engine_eval = analyzer.analyze(board)
            positions.append(
                PositionSnapshot(
                    game_index=index,
                    move_number=move_num,
                    san=san,
                    fen=board.fen(),
                    eval_before=eval_before,
                    eval_after=engine_eval["eval"],
                    eval_shift=eval_shift,
                    board_ascii=str(board),
                )
            )

            if board.turn == chess.BLACK and eval_before is not None:
                white_eval_at_move[move_num] = eval_before
            elif board.turn == chess.WHITE and eval_before is not None and move_num in white_eval_at_move:
                black_from_white_pov = -eval_before
                divergence = abs(white_eval_at_move[move_num] - black_from_white_pov)
                if divergence >= 0.5:
                    divergences.append(
                        {
                            "move": move_num,
                            "white_eval": white_eval_at_move[move_num],
                            "black_eval": black_from_white_pov,
                            "gap": round(divergence, 2),
                            "white": white,
                            "black": black,
                        }
                    )

        critical = sorted(
            [p for p in positions if p.eval_shift is not None], key=lambda p: abs(p.eval_shift or 0), reverse=True
        )[:4]

        return {
            "index": index,
            "white": white,
            "black": black,
            "result": game.headers.get("Result", "*"),
            "positions": positions,
            "critical": critical,
            "divergences": sorted(divergences, key=lambda d: d["gap"], reverse=True)[:4],
            "pawn_summary": self._describe_pawn_structure(positions),
            "plans": self._infer_plans(positions),
        }

    def _describe_pawn_structure(self, positions: List[PositionSnapshot]) -> str:
        if not positions:
            return "No middlegame positions available."
        target = min(positions, key=lambda p: abs(p.move_number - 20))
        board = chess.Board(target.fen)

        white_center = sum(
            1
            for sq in (chess.D4, chess.E4)
            if board.piece_at(sq) and board.piece_at(sq).piece_type == chess.PAWN and board.piece_at(sq).color == chess.WHITE
        )
        black_center = sum(
            1
            for sq in (chess.D5, chess.E5)
            if board.piece_at(sq) and board.piece_at(sq).piece_type == chess.PAWN and board.piece_at(sq).color == chess.BLACK
        )

        files = "abcdefgh"
        white_files = sorted(
            {
                files[chess.square_file(sq)]
                for sq in chess.SQUARES
                if board.piece_at(sq) and board.piece_at(sq).piece_type == chess.PAWN and board.piece_at(sq).color == chess.WHITE
            }
        )
        black_files = sorted(
            {
                files[chess.square_file(sq)]
                for sq in chess.SQUARES
                if board.piece_at(sq) and board.piece_at(sq).piece_type == chess.PAWN and board.piece_at(sq).color == chess.BLACK
            }
        )
        tension = "balanced" if abs(white_center - black_center) <= 1 else "imbalanced"
        return (
            f"Move {target.move_number} structure: White pawns on {', '.join(white_files) or '-'}; "
            f"Black pawns on {', '.join(black_files) or '-'}; center tension {tension}."
        )

    def _infer_plans(self, positions: List[PositionSnapshot]) -> List[str]:
        themes: Counter = Counter()
        for pos in positions:
            board = chess.Board(pos.fen)
            if board.has_kingside_castling_rights(chess.WHITE) or board.has_kingside_castling_rights(chess.BLACK):
                themes["Development race and king safety still matter"] += 1
            if self._open_file_pressure(board, chess.WHITE):
                themes["White often gets open-file rook activity"] += 1
            if self._open_file_pressure(board, chess.BLACK):
                themes["Black often gets open-file rook activity"] += 1
            if self._knight_outpost(board, chess.WHITE):
                themes["White can target outpost squares for long-term pressure"] += 1
            if self._knight_outpost(board, chess.BLACK):
                themes["Black can target outpost squares for long-term pressure"] += 1
            if self._queens_on(board):
                themes["Middlegame keeps tactical queen-based opportunities"] += 1

        if not themes:
            return ["Play by piece activity and king safety; no dominant recurring theme detected."]
        return [plan for plan, _ in themes.most_common(4)]

    @staticmethod
    def _queens_on(board: chess.Board) -> bool:
        return bool(board.pieces(chess.QUEEN, chess.WHITE) and board.pieces(chess.QUEEN, chess.BLACK))

    @staticmethod
    def _open_file_pressure(board: chess.Board, color: chess.Color) -> bool:
        for rook_sq in board.pieces(chess.ROOK, color):
            file_idx = chess.square_file(rook_sq)
            has_own_pawn = any(
                board.piece_at(chess.square(file_idx, r))
                and board.piece_at(chess.square(file_idx, r)).piece_type == chess.PAWN
                and board.piece_at(chess.square(file_idx, r)).color == color
                for r in range(8)
            )
            if not has_own_pawn:
                return True
        return False

    @staticmethod
    def _knight_outpost(board: chess.Board, color: chess.Color) -> bool:
        enemy = not color
        for sq in board.pieces(chess.KNIGHT, color):
            rank = chess.square_rank(sq)
            advanced = rank >= 4 if color == chess.WHITE else rank <= 3
            if not advanced:
                continue
            enemy_pawn_attacks = any(
                board.piece_at(a)
                and board.piece_at(a).piece_type == chess.PAWN
                and board.piece_at(a).color == enemy
                for a in board.attackers(enemy, sq)
            )
            if not enemy_pawn_attacks:
                return True
        return False

    def _build_report(self, games: List[Dict], timestamp: str) -> str:
        total = len(games)
        results = Counter(g["result"] for g in games)
        wins = results.get("1-0", 0)
        losses = results.get("0-1", 0)
        draws = results.get("1/2-1/2", 0)

        lines: List[str] = [
            f"# {self.opening_name} - Engine Analysis Report",
            "",
            "## Games Analyzed",
            f"- {total} games",
            f"- Results: {wins}W {draws}D {losses}L",
            "",
            "## Middlegame Overview",
            f"Positions analyzed: Moves {self.MIDDLEGAME_START}-{self.MIDDLEGAME_END}",
            "- Move 15-20: Early middlegame structure and piece regrouping",
            "- Move 21-28: Typical tactical/strategic pressure phase",
            "- Move 29-35: Transition decisions before endgame",
            "",
            "## Typical Pawn Structure",
            games[0]["pawn_summary"],
            "",
            "```text",
            self._board_for_example(games),
            "```",
            "",
            "## Engine Divergence",
        ]

        divergences = [d for g in games for d in g["divergences"]]
        if divergences:
            for d in sorted(divergences, key=lambda x: x["gap"], reverse=True)[:8]:
                lines.append(
                    f"- Move {d['move']}: {d['white']} eval {d['white_eval']:+.2f}, "
                    f"{d['black']} eval {d['black_eval']:+.2f} (gap {d['gap']:+.2f})"
                )
        else:
            lines.append("- No significant divergence detected from PGN eval comments.")

        lines.extend(["", "## Key Plans Identified"]) 
        plan_counter = Counter(plan for g in games for plan in g["plans"])
        for i, (plan, _) in enumerate(plan_counter.most_common(5), start=1):
            lines.append(f"{i}. {plan}")

        lines.extend(["", "## Critical Positions", ""])
        critical = [p for g in games for p in g["critical"]]
        if critical:
            for pos in sorted(critical, key=lambda p: abs(p.eval_shift or 0), reverse=True)[:10]:
                lines.append(
                    f"- Game {pos.game_index}, move {pos.move_number} ({pos.san}): "
                    f"engine eval {pos.eval_after:+.2f}, shift {pos.eval_shift:+.2f}"
                )
        else:
            lines.append("- No critical shifts identified from available move comments.")

        lines.extend(
            [
                "",
                "## Repertoire Recommendation",
                self._recommendation(games),
                "",
                "---",
                f"Generated: {timestamp}",
            ]
        )
        return "\n".join(lines)

    def _board_for_example(self, games: List[Dict]) -> str:
        first = games[0]["positions"]
        if not first:
            return "No middlegame board available."
        sample = min(first, key=lambda p: abs(p.move_number - 20))
        return sample.board_ascii

    def _recommendation(self, games: List[Dict]) -> str:
        evaluations = [p.eval_after for g in games for p in g["positions"] if p.eval_after is not None]
        if not evaluations:
            return "→ Insufficient evaluated middlegame positions to make a recommendation."

        avg = sum(evaluations) / len(evaluations)
        volatility = max(evaluations) - min(evaluations)
        if abs(avg) <= 0.35 and volatility < 2.0:
            return "✓ Sound practical choice: engines keep positions near equality with manageable middlegame plans."
        if avg > 0.35:
            return "✓ Promising for White repertoire: recurring middlegame edge appears in analyzed games."
        return "→ Viable but sharp for Black repertoire: study critical move-order choices before adopting widely."
