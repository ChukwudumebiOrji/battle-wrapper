"""
repertoire_analyzer.py

Analyzes engine vs engine games to extract middlegame knowledge for opening
repertoire building. Focuses on positions from moves 15-35, engine evaluation
divergence between STOCKFISH and VIRIDITHAS, and key strategic plan identification.
"""

import re
import datetime
import pathlib
import chess
import chess.pgn
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple, Any


class RepertoireAnalyzer:
    """
    Reads engine battle PGN files and produces a structured markdown report covering:
    - Opening overview (games played, results)
    - Typical middlegame pawn structures and piece placements (moves 15-35)
    - Engine evaluation divergence (where STOCKFISH and VIRIDITHAS disagree most)
    - Positional themes and recurring plans
    - Critical decision points (moves with the largest evaluation shifts)
    - Repertoire recommendations
    """

    EARLY_MG_START = 15
    EARLY_MG_END = 25
    LATE_MG_START = 25
    LATE_MG_END = 35
    DIVERGENCE_THRESHOLD = 1.0   # CP gap to flag significant engine disagreement
    CRITICAL_SHIFT = 0.5         # CP shift to flag a critical move

    _FILE_NAMES = "abcdefgh"

    def __init__(self, pgn_path: pathlib.Path, opening_name: str):
        self.pgn_path = pathlib.Path(pgn_path)
        self.opening_name = opening_name

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def analyze_and_report(self, output_dir: pathlib.Path) -> pathlib.Path:
        """Run full analysis and write a markdown report. Returns the report path."""
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%d-%m_%H-%M")
        report_path = output_dir / f"{self.opening_name}-Report-{timestamp}.md"

        games = self._load_engine_games()
        if not games:
            report_path.write_text(
                f"# {self.opening_name} Repertoire Report\n\n"
                "*No engine vs engine games found in the supplied PGN.*\n",
                encoding="utf-8",
            )
            print(f"[+] Repertoire report written to: {report_path}")
            return report_path

        analyses = [self._analyze_game(g) for g in games]
        report_path.write_text(self._build_report(analyses, timestamp), encoding="utf-8")
        print(f"[+] Repertoire report written to: {report_path}")
        return report_path

    # ------------------------------------------------------------------
    # PGN loading helpers
    # ------------------------------------------------------------------

    def _load_engine_games(self) -> List[chess.pgn.Game]:
        """Load only engine vs engine games from the PGN file."""
        if not self.pgn_path.exists():
            return []
        engine_names = {"stockfish", "viridithas"}
        games = []
        with open(self.pgn_path, encoding="utf-8") as f:
            while True:
                game = chess.pgn.read_game(f)
                if game is None:
                    break
                white = game.headers.get("White", "").lower()
                black = game.headers.get("Black", "").lower()
                if any(e in white for e in engine_names) and any(e in black for e in engine_names):
                    games.append(game)
        return games

    # ------------------------------------------------------------------
    # PGN evaluation parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_eval(comment: str) -> Optional[float]:
        """
        Extract the centipawn score from a PGN move comment.
        Handles formats like '+0.58/15 0.58s', '-1.23/20 0.1s', '#5', etc.
        Returns None for book moves or unparseable comments.
        """
        if not comment or "book" in comment.lower():
            return None
        # Handle mate annotations: #+N or #-N
        mate_match = re.search(r'#([+-]?\d+)', comment)
        if mate_match:
            mate_in = int(mate_match.group(1))
            return 100.0 if mate_in > 0 else -100.0
        # Standard centipawn score: +0.58/15 or -1.23
        cp_match = re.search(r'([+-]?\d+\.\d+)/', comment)
        if cp_match:
            try:
                return float(cp_match.group(1))
            except ValueError:
                pass
        return None

    # ------------------------------------------------------------------
    # Board / position analysis helpers
    # ------------------------------------------------------------------

    def _pawn_features(self, board: chess.Board) -> Dict[str, Any]:
        """
        Return a dictionary describing the current pawn structure:
        white/black pawn file sets, isolated, doubled and passed pawns.
        """
        white_pawns: List[Tuple[int, int, str]] = []
        black_pawns: List[Tuple[int, int, str]] = []

        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            if piece and piece.piece_type == chess.PAWN:
                fi = chess.square_file(sq)
                rk = chess.square_rank(sq) + 1
                notation = f"{self._FILE_NAMES[fi]}{rk}"
                if piece.color == chess.WHITE:
                    white_pawns.append((fi, rk, notation))
                else:
                    black_pawns.append((fi, rk, notation))

        white_files = {p[0] for p in white_pawns}
        black_files = {p[0] for p in black_pawns}

        def isolated(pawns, own_files):
            result = []
            for fi, rk, notation in pawns:
                adj = {fi - 1, fi + 1} & set(range(8))
                if not (adj & own_files):
                    result.append(notation)
            return result

        def doubled(pawns):
            counts = Counter(p[0] for p in pawns)
            return [self._FILE_NAMES[f] for f, c in counts.items() if c > 1]

        def passed(pawns, enemy_pawns, color_is_white):
            result = []
            for fi, rk, notation in pawns:
                adj_files = {fi - 1, fi, fi + 1} & set(range(8))
                if color_is_white:
                    blocking = [p for p in enemy_pawns if p[0] in adj_files and p[1] > rk]
                else:
                    blocking = [p for p in enemy_pawns if p[0] in adj_files and p[1] < rk]
                if not blocking:
                    result.append(notation)
            return result

        return {
            "white_pawns": white_pawns,
            "black_pawns": black_pawns,
            "isolated_white": isolated(white_pawns, white_files),
            "isolated_black": isolated(black_pawns, black_files),
            "doubled_white": doubled(white_pawns),
            "doubled_black": doubled(black_pawns),
            "passed_white": passed(white_pawns, black_pawns, True),
            "passed_black": passed(black_pawns, white_pawns, False),
        }

    def _describe_pawn_structure(self, features: Dict) -> str:
        """Convert pawn feature dict into a human-readable string."""
        parts = []
        if features["white_pawns"]:
            files = sorted({self._FILE_NAMES[p[0]] for p in features["white_pawns"]})
            parts.append(f"White pawns on {', '.join(files)}")
        if features["black_pawns"]:
            files = sorted({self._FILE_NAMES[p[0]] for p in features["black_pawns"]})
            parts.append(f"Black pawns on {', '.join(files)}")
        if features["isolated_white"]:
            parts.append(f"Isolated white pawns: {', '.join(features['isolated_white'])}")
        if features["isolated_black"]:
            parts.append(f"Isolated black pawns: {', '.join(features['isolated_black'])}")
        if features["doubled_white"]:
            parts.append(f"Doubled white pawns on {'-'.join(features['doubled_white'])} file(s)")
        if features["doubled_black"]:
            parts.append(f"Doubled black pawns on {'-'.join(features['doubled_black'])} file(s)")
        if features["passed_white"]:
            parts.append(f"White passed pawns: {', '.join(features['passed_white'])}")
        if features["passed_black"]:
            parts.append(f"Black passed pawns: {', '.join(features['passed_black'])}")
        return "; ".join(parts) if parts else "Pawns exchanged / minimal pawn structure"

    def _piece_placements(self, board: chess.Board, color: chess.Color) -> List[str]:
        """
        Return annotated piece placements for the given color (excluding pawns).
        Annotations include: outpost knights, open/half-open file rooks, good/bad bishops.
        """
        _names = {
            chess.KNIGHT: "Knight", chess.BISHOP: "Bishop",
            chess.ROOK: "Rook", chess.QUEEN: "Queen", chess.KING: "King",
        }
        placements = []
        enemy = not color

        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            if not piece or piece.color != color or piece.piece_type == chess.PAWN:
                continue

            name = _names.get(piece.piece_type, "")
            sq_name = chess.square_name(sq)
            fi = chess.square_file(sq)
            rk = chess.square_rank(sq)
            annotation = ""

            if piece.piece_type == chess.KNIGHT:
                adv_rank = rk >= 4 if color == chess.WHITE else rk <= 3
                supported = any(
                    board.piece_at(s) and board.piece_at(s).piece_type == chess.PAWN
                    for s in board.attackers(color, sq)
                )
                enemy_pawn_attacks = any(
                    board.piece_at(s) and board.piece_at(s).piece_type == chess.PAWN
                    for s in board.attackers(enemy, sq)
                )
                if adv_rank and supported and not enemy_pawn_attacks:
                    annotation = " (outpost)"

            elif piece.piece_type == chess.ROOK:
                own_pawn = any(
                    board.piece_at(chess.square(fi, r)) is not None
                    and board.piece_at(chess.square(fi, r)).piece_type == chess.PAWN
                    and board.piece_at(chess.square(fi, r)).color == color
                    for r in range(8)
                )
                enemy_pawn = any(
                    board.piece_at(chess.square(fi, r)) is not None
                    and board.piece_at(chess.square(fi, r)).piece_type == chess.PAWN
                    and board.piece_at(chess.square(fi, r)).color == enemy
                    for r in range(8)
                )
                if not own_pawn and not enemy_pawn:
                    annotation = " (open file)"
                elif not own_pawn:
                    annotation = " (half-open file)"

            elif piece.piece_type == chess.BISHOP:
                bishop_color = (fi + rk) % 2
                center_files = {3, 4}
                center_pawns = [
                    s for s in chess.SQUARES
                    if board.piece_at(s) and board.piece_at(s).piece_type == chess.PAWN
                    and board.piece_at(s).color == color
                    and chess.square_file(s) in center_files
                ]
                if center_pawns:
                    pawn_colors = [(chess.square_file(s) + chess.square_rank(s)) % 2 for s in center_pawns]
                    if all(c == bishop_color for c in pawn_colors):
                        annotation = " (bad bishop)"
                    elif all(c != bishop_color for c in pawn_colors):
                        annotation = " (good bishop)"

            placements.append(f"{name} on {sq_name}{annotation}")

        return placements

    def _positional_themes(self, board: chess.Board) -> List[str]:
        """Detect high-level positional themes from the board state."""
        themes = []

        # Space advantage
        white_space = sum(
            1 for sq in chess.SquareSet(
                chess.BB_RANKS[4] | chess.BB_RANKS[5] | chess.BB_RANKS[6] | chess.BB_RANKS[7]
            ) if board.is_attacked_by(chess.WHITE, sq)
        )
        black_space = sum(
            1 for sq in chess.SquareSet(
                chess.BB_RANKS[0] | chess.BB_RANKS[1] | chess.BB_RANKS[2] | chess.BB_RANKS[3]
            ) if board.is_attacked_by(chess.BLACK, sq)
        )
        if white_space > black_space + 5:
            themes.append("White has clear space advantage")
        elif black_space > white_space + 5:
            themes.append("Black has clear space advantage")
        elif white_space > black_space + 2:
            themes.append("White has modest space advantage")
        elif black_space > white_space + 2:
            themes.append("Black has modest space advantage")

        # Castling status
        if board.has_castling_rights(chess.WHITE):
            themes.append("White king uncastled")
        if board.has_castling_rights(chess.BLACK):
            themes.append("Black king uncastled")

        # Open file near kings
        for color, label in ((chess.WHITE, "White"), (chess.BLACK, "Black")):
            king_sq = board.king(color)
            if king_sq is None:
                continue
            kf = chess.square_file(king_sq)
            open_near_king = any(
                not any(
                    board.piece_at(chess.square(f, r)) is not None
                    and board.piece_at(chess.square(f, r)).piece_type == chess.PAWN
                    for r in range(8)
                )
                for f in [kf - 1, kf, kf + 1]
                if 0 <= f <= 7
            )
            if open_near_king:
                themes.append(f"Open file near {label} king (king safety concern)")

        # Material imbalance
        piece_values = {chess.QUEEN: 9, chess.ROOK: 5, chess.BISHOP: 3, chess.KNIGHT: 3}
        white_mat = sum(
            piece_values.get(board.piece_at(sq).piece_type, 0)
            for sq in chess.SQUARES
            if board.piece_at(sq) and board.piece_at(sq).color == chess.WHITE
            and board.piece_at(sq).piece_type != chess.PAWN
        )
        black_mat = sum(
            piece_values.get(board.piece_at(sq).piece_type, 0)
            for sq in chess.SQUARES
            if board.piece_at(sq) and board.piece_at(sq).color == chess.BLACK
            and board.piece_at(sq).piece_type != chess.PAWN
        )
        diff = white_mat - black_mat
        if diff >= 3:
            themes.append(f"White has material advantage (+{diff} pts)")
        elif diff <= -3:
            themes.append(f"Black has material advantage (+{-diff} pts)")

        return themes

    # ------------------------------------------------------------------
    # Per-game analysis
    # ------------------------------------------------------------------

    def _analyze_game(self, game: chess.pgn.Game) -> Dict[str, Any]:
        """
        Extract structured analysis from a single game.
        Returns a dict with all data needed to build the report section.
        """
        white = game.headers.get("White", "Unknown")
        black = game.headers.get("Black", "Unknown")
        result = game.headers.get("Result", "*")
        opening_header = game.headers.get("Opening", "Unknown")
        variation_header = game.headers.get("Variation", "")
        full_opening = f"{opening_header}: {variation_header}" if variation_header else opening_header

        move_records: List[Dict[str, Any]] = []
        board = game.board()
        move_num = 1

        node = game
        while node.variations:
            node = node.variations[0]
            move = node.move
            comment = node.comment or ""
            eval_val = self._parse_eval(comment)
            side = "white" if board.turn == chess.WHITE else "black"

            snapshot: Optional[chess.Board] = None
            if self.EARLY_MG_START <= move_num <= self.LATE_MG_END:
                snapshot = board.copy()

            move_records.append({
                "move_num": move_num,
                "side": side,
                "uci": move.uci(),
                "san": board.san(move),
                "eval": eval_val,
                "board_snapshot": snapshot,
            })

            board.push(move)
            if side == "black":
                move_num += 1

        # --- Critical decision points (eval shift >= CRITICAL_SHIFT) ---
        critical_points: List[Dict] = []
        for i in range(1, len(move_records)):
            prev = move_records[i - 1]
            curr = move_records[i]
            if prev["eval"] is None or curr["eval"] is None:
                continue
            # Normalize both to white's perspective
            prev_wp = prev["eval"] if prev["side"] == "white" else -prev["eval"]
            curr_wp = curr["eval"] if curr["side"] == "white" else -curr["eval"]
            shift = abs(curr_wp - prev_wp)
            if shift >= self.CRITICAL_SHIFT:
                critical_points.append({
                    "move_num": curr["move_num"],
                    "side": curr["side"],
                    "san": curr["san"],
                    "eval_before": prev_wp,
                    "eval_after": curr_wp,
                    "shift": shift,
                })

        # --- Engine divergence per full move ---
        # White's eval after white's move vs Black's eval (normalized) after black's move.
        # Group by move_num to compare the two engines in the same move number.
        by_move: Dict[int, Dict[str, Dict]] = defaultdict(dict)
        for rec in move_records:
            by_move[rec["move_num"]][rec["side"]] = rec

        divergences: List[Dict] = []
        for mv_num in sorted(by_move):
            sides = by_move[mv_num]
            if "white" not in sides or "black" not in sides:
                continue
            we = sides["white"]["eval"]
            be = sides["black"]["eval"]
            if we is None or be is None:
                continue
            # Normalize black's eval to white's perspective
            be_norm = -be
            divergence = abs(we - be_norm)
            if divergence >= self.DIVERGENCE_THRESHOLD:
                divergences.append({
                    "move_num": mv_num,
                    "white_eval": we,
                    "black_eval_norm": be_norm,
                    "divergence": divergence,
                    "white_san": sides["white"]["san"],
                    "black_san": sides["black"]["san"],
                    "white_engine": white,
                    "black_engine": black,
                })

        # --- Position snapshots: early and late middlegame ---
        def _build_pos_snapshot(rec: Dict) -> Dict:
            b = rec["board_snapshot"]
            pf = self._pawn_features(b)
            return {
                "move_num": rec["move_num"],
                "side": rec["side"],
                "san": rec["san"],
                "pawn_structure": self._describe_pawn_structure(pf),
                "pawn_features": pf,
                "white_pieces": self._piece_placements(b, chess.WHITE),
                "black_pieces": self._piece_placements(b, chess.BLACK),
                "themes": self._positional_themes(b),
                "eval": rec["eval"],
            }

        early_mg = [
            _build_pos_snapshot(rec)
            for rec in move_records
            if rec["board_snapshot"] is not None
            and self.EARLY_MG_START <= rec["move_num"] < self.EARLY_MG_END
        ]
        late_mg = [
            _build_pos_snapshot(rec)
            for rec in move_records
            if rec["board_snapshot"] is not None
            and self.LATE_MG_START <= rec["move_num"] < self.LATE_MG_END
        ]

        # Eval timeline (white's perspective), one entry per full move number.
        # Use Black's eval when available (reflects position after both sides moved),
        # otherwise fall back to White's eval.
        seen_move_nums: Dict[int, float] = {}
        for rec in move_records:
            if rec["eval"] is None:
                continue
            wp = rec["eval"] if rec["side"] == "white" else -rec["eval"]
            # Black's entry (side=="black") overwrites White's for the same move_num,
            # giving one representative eval per full move.
            seen_move_nums[rec["move_num"]] = wp
        eval_timeline = sorted(seen_move_nums.items())

        return {
            "white": white,
            "black": black,
            "result": result,
            "opening": full_opening,
            "move_count": move_num - 1,
            "critical_points": critical_points,
            "divergences": divergences,
            "early_mg": early_mg,
            "late_mg": late_mg,
            "eval_timeline": eval_timeline,
        }

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    def _build_report(self, analyses: List[Dict], timestamp: str) -> str:
        lines: List[str] = []

        # Title
        lines += [
            f"# {self.opening_name} Opening Repertoire Report",
            f"*Generated: {timestamp}*",
            "",
        ]

        self._section_overview(lines, analyses)
        self._section_middlegame(lines, analyses)
        self._section_engine_comparison(lines, analyses)
        self._section_plans_and_themes(lines, analyses)
        self._section_critical_points(lines, analyses)
        self._section_recommendations(lines, analyses)

        lines.append(
            f"---\n*Report generated by Battle Wrapper Repertoire Analyzer — {timestamp}*"
        )
        return "\n".join(lines)

    # --- Section builders ---

    def _section_overview(self, lines: List[str], analyses: List[Dict]) -> None:
        total = len(analyses)
        w_wins = sum(1 for a in analyses if a["result"] == "1-0")
        b_wins = sum(1 for a in analyses if a["result"] == "0-1")
        draws = sum(1 for a in analyses if a["result"] == "1/2-1/2")

        lines += [
            "---",
            "## Opening Overview",
            "",
            f"- **Games Analyzed:** {total}",
            f"- **Results:** {w_wins} White win(s) | {b_wins} Black win(s) | {draws} Draw(s)",
            "",
            "**Openings Encountered:**",
        ]

        op_counter: Counter = Counter(a["opening"] for a in analyses)
        for op, count in op_counter.most_common():
            subset = [a for a in analyses if a["opening"] == op]
            w = sum(1 for a in subset if a["result"] == "1-0")
            b = sum(1 for a in subset if a["result"] == "0-1")
            d = sum(1 for a in subset if a["result"] == "1/2-1/2")
            lines.append(f"- {op} — {count} game(s): {w}W / {b}L / {d}D")

        lines += ["", "**Individual Games:**"]
        for i, a in enumerate(analyses, 1):
            lines.append(
                f"- Game {i}: {a['white']} vs {a['black']} → **{a['result']}** "
                f"({a['move_count']} moves) — {a['opening']}"
            )
        lines.append("")

    def _section_middlegame(self, lines: List[str], analyses: List[Dict]) -> None:
        lines += ["---", "## Typical Middlegame Positions", ""]

        for label, start, end, key in (
            ("Early", self.EARLY_MG_START, self.EARLY_MG_END, "early_mg"),
            ("Late", self.LATE_MG_START, self.LATE_MG_END, "late_mg"),
        ):
            lines.append(f"### {label} Middlegame (Moves {start}–{end})")
            lines.append("")

            all_pos = [p for a in analyses for p in a[key]]
            if not all_pos:
                lines.append(
                    "*No positions captured in this range "
                    "(games may have ended or been short-circuited).*"
                )
                lines.append("")
                continue

            # Pawn structures
            struct_counts = Counter(p["pawn_structure"] for p in all_pos)
            lines.append("**Pawn Structures:**")
            for ps, cnt in struct_counts.most_common(3):
                lines.append(f"- ({cnt}x) {ps}")
            lines.append("")

            # Representative position snapshot near mid-range
            mid = (start + end) // 2
            samples = sorted(all_pos, key=lambda p: abs(p["move_num"] - mid))[:2]
            lines.append("**Key Piece Placements:**")
            for pos in samples:
                eval_str = f"{pos['eval']:+.2f}" if pos["eval"] is not None else "n/a"
                lines.append(f"- *Move {pos['move_num']} ({pos['side'].capitalize()} plays {pos['san']}, eval {eval_str}):*")
                for wp in pos["white_pieces"][:5]:
                    lines.append(f"  - White: {wp}")
                for bp in pos["black_pieces"][:5]:
                    lines.append(f"  - Black: {bp}")
            lines.append("")

            # Positional themes
            all_themes = [t for p in all_pos for t in p["themes"]]
            theme_counts = Counter(all_themes)
            if theme_counts:
                lines.append("**Positional Themes:**")
                for theme, cnt in theme_counts.most_common(5):
                    lines.append(f"- {theme} (seen {cnt}x)")
                lines.append("")

    def _section_engine_comparison(self, lines: List[str], analyses: List[Dict]) -> None:
        lines += ["---", "## Engine Comparison", ""]

        all_div = []
        for i, a in enumerate(analyses, 1):
            for d in a["divergences"]:
                all_div.append({**d, "game_num": i})

        if not all_div:
            lines += [
                f"*No positions found where engines disagreed by more than "
                f"{self.DIVERGENCE_THRESHOLD:.1f} CP.*",
                "",
            ]
            return

        all_div.sort(key=lambda x: x["divergence"], reverse=True)

        lines += [
            f"**Total positions with divergence >{self.DIVERGENCE_THRESHOLD:.1f} CP:** {len(all_div)}",
            "",
            "**Top Engine Disagreements:**",
        ]
        for d in all_div[:10]:
            we = d["white_eval"]
            be = d["black_eval_norm"]
            stronger = d["white_engine"] if we > be else d["black_engine"]
            lines.append(
                f"- Game {d['game_num']}, Move {d['move_num']}: "
                f"{d['white_engine']} eval {we:+.2f} vs {d['black_engine']} eval {be:+.2f} "
                f"(gap: {d['divergence']:.2f} CP) "
                f"→ *{stronger} assessed position more accurately*"
            )
        lines.append("")

        # Aggregate: which engine was more optimistic (had higher normalized eval)
        sf_up = sum(
            1 for d in all_div
            if (d["white_engine"].upper() == "STOCKFISH" and d["white_eval"] > d["black_eval_norm"])
            or (d["black_engine"].upper() == "STOCKFISH" and d["black_eval_norm"] > d["white_eval"])
        )
        vir_up = len(all_div) - sf_up

        lines += [
            "**Engine Assessment Summary:**",
            f"- STOCKFISH held a more favorable eval: {sf_up} time(s)",
            f"- VIRIDITHAS held a more favorable eval: {vir_up} time(s)",
            "",
            "**Game Results:**",
        ]
        for i, a in enumerate(analyses, 1):
            winner_str = (
                "Draw" if a["result"] == "1/2-1/2"
                else (a["white"] if a["result"] == "1-0" else a["black"])
            )
            lines.append(
                f"- Game {i}: {a['white']} vs {a['black']} → {a['result']} ({winner_str})"
            )
        lines.append("")

        # Show where engines made different moves at divergence points
        lines.append("**Divergent Move Choices:**")
        for d in all_div[:6]:
            lines.append(
                f"- Move {d['move_num']} (Game {d['game_num']}): "
                f"{d['white_engine']} played **{d['white_san']}**, "
                f"{d['black_engine']} played **{d['black_san']}**"
            )
        lines.append("")

    def _section_plans_and_themes(self, lines: List[str], analyses: List[Dict]) -> None:
        lines += ["---", "## Positional Plans and Themes", ""]

        early_themes = [t for a in analyses for p in a["early_mg"] for t in p["themes"]]
        late_themes = [t for a in analyses for p in a["late_mg"] for t in p["themes"]]

        if early_themes:
            lines.append(f"**Early Middlegame Plans (moves {self.EARLY_MG_START}–{self.EARLY_MG_END}):**")
            for theme, cnt in Counter(early_themes).most_common(6):
                lines.append(f"- {theme} (occurred {cnt}x)")
            lines.append("")

        if late_themes:
            lines.append(f"**Late Middlegame Plans (moves {self.LATE_MG_START}–{self.LATE_MG_END}):**")
            for theme, cnt in Counter(late_themes).most_common(6):
                lines.append(f"- {theme} (occurred {cnt}x)")
            lines.append("")

        # Recurring isolated pawn patterns
        iso_w = sum(1 for a in analyses for p in a["early_mg"] if p["pawn_features"]["isolated_white"])
        iso_b = sum(1 for a in analyses for p in a["early_mg"] if p["pawn_features"]["isolated_black"])
        if iso_w or iso_b:
            lines.append("**Structural Weaknesses (Early Middlegame):**")
            if iso_w:
                lines.append(f"- Isolated white pawns appeared in {iso_w} position(s)")
            if iso_b:
                lines.append(f"- Isolated black pawns appeared in {iso_b} position(s)")
            lines.append("")

        # Recurring pawn structures across all games
        all_structs = [p["pawn_structure"] for a in analyses for p in a["early_mg"]]
        recurring = [(ps, c) for ps, c in Counter(all_structs).most_common(3) if c > 1]
        if recurring:
            lines.append("**Recurring Pawn Structures (Early Middlegame):**")
            for ps, cnt in recurring:
                lines.append(f"- Appeared {cnt}x: {ps}")
            lines.append("")

        if not early_themes and not late_themes:
            lines.append(
                "*Insufficient middlegame position data to extract recurring plans. "
                "Run more games for stronger pattern detection.*"
            )
            lines.append("")

    def _section_critical_points(self, lines: List[str], analyses: List[Dict]) -> None:
        lines += ["---", "## Critical Decision Points", ""]

        all_cp = []
        for i, a in enumerate(analyses, 1):
            for cp in a["critical_points"]:
                all_cp.append({**cp, "game_num": i, "game_str": f"{a['white']} vs {a['black']}"})

        if not all_cp:
            lines += ["*No significant evaluation shifts detected.*", ""]
            return

        all_cp.sort(key=lambda x: x["shift"], reverse=True)

        lines.append("**Most Significant Turning Points:**")
        for cp in all_cp[:10]:
            arrow = "↑" if cp["eval_after"] > cp["eval_before"] else "↓"
            lines.append(
                f"- Game {cp['game_num']} ({cp['game_str']}), "
                f"Move {cp['move_num']} ({cp['side'].capitalize()}): **{cp['san']}** "
                f"— eval {cp['eval_before']:+.2f} → {cp['eval_after']:+.2f} "
                f"({arrow}{cp['shift']:.2f} CP)"
            )
        lines.append("")

        # Evaluation timeline table for the longest game
        if analyses:
            best = max(analyses, key=lambda a: a["move_count"])
            timeline = [(mn, ev) for mn, ev in best["eval_timeline"] if mn % 5 == 0]
            if timeline:
                lines.append(
                    f"**Evaluation Progression — {best['white']} vs {best['black']} "
                    f"(every 5 moves, White perspective):**"
                )
                lines += ["| Move | Eval | Trend |", "|------|------|-------|"]
                prev_ev = 0.0
                for mn, ev in timeline[:15]:
                    trend = "▲" if ev > prev_ev + 0.1 else ("▼" if ev < prev_ev - 0.1 else "—")
                    lines.append(f"| {mn} | {ev:+.2f} | {trend} |")
                    prev_ev = ev
                lines.append("")

    def _section_recommendations(self, lines: List[str], analyses: List[Dict]) -> None:
        lines += ["---", "## Repertoire Recommendations", ""]
        lines.append(
            f"Based on {len(analyses)} engine game(s) in the **{self.opening_name}**, "
            "here are key insights for building your repertoire:"
        )
        lines.append("")

        recs: List[str] = []

        # 1 — Opening soundness from eval at move ~15
        evals_at_15 = [
            p["eval"]
            for a in analyses
            for p in a["early_mg"]
            if p["eval"] is not None and abs(p["move_num"] - 15) <= 2
        ]
        if evals_at_15:
            # Normalize to white perspective (early_mg stores raw engine evals)
            avg = sum(evals_at_15) / len(evals_at_15)
            if abs(avg) <= 0.3:
                recs.append(
                    f"✅ **Opening Soundness:** The position is balanced around move 15 "
                    f"(avg eval {avg:+.2f}). This is a reliable repertoire choice."
                )
            elif avg > 0.3:
                recs.append(
                    f"⚠️ **White Advantage:** Engine evaluations around move 15 slightly "
                    f"favour White (avg {avg:+.2f}). As Black, prepare for a defensive but "
                    "rich middlegame."
                )
            else:
                recs.append(
                    f"ℹ️ **Black Counter-Play:** Evaluations around move 15 lean toward "
                    f"Black (avg {avg:+.2f}), suggesting this opening creates active "
                    "counter-play opportunities."
                )

        # 2 — Pawn structure warning
        iso_b_total = sum(1 for a in analyses for p in a["early_mg"] if p["pawn_features"]["isolated_black"])
        if iso_b_total:
            recs.append(
                f"⚠️ **Pawn Structure:** Black's isolated pawns appeared in {iso_b_total} "
                "early-middlegame positions. Prioritize active piece play to compensate."
            )

        # 3 — Most significant divergence point
        all_div = sorted(
            (d for a in analyses for d in a["divergences"]),
            key=lambda d: d["divergence"], reverse=True
        )
        if all_div:
            top = all_div[0]
            recs.append(
                f"🔍 **Key Learning Position:** Move {top['move_num']} showed the largest "
                f"engine disagreement ({top['divergence']:.2f} CP). Study this moment carefully "
                "— both engines chose different strategic plans, marking a critical crossroads."
            )

        # 4 — Most critical early move
        early_cp = sorted(
            (cp for a in analyses for cp in a["critical_points"] if cp["move_num"] <= 20),
            key=lambda x: x["shift"], reverse=True
        )
        if early_cp:
            top_cp = early_cp[0]
            recs.append(
                f"📌 **Critical Opening Move:** Move {top_cp['move_num']} ({top_cp['san']}) "
                f"was the most impactful early decision ({top_cp['shift']:.2f} CP shift). "
                "Ensure you understand the plans arising after this move."
            )

        # 5 — Space/king-safety theme
        space_themes = [
            t for a in analyses for p in a["early_mg"] for t in p["themes"]
            if "space" in t.lower() or "king" in t.lower()
        ]
        if space_themes:
            top_theme = Counter(space_themes).most_common(1)[0][0]
            recs.append(
                f"♟️ **Recurring Theme:** '{top_theme}' appeared frequently in the early "
                "middlegame. Build plans around this structural feature."
            )

        if not recs:
            recs.append(
                f"Run more games to generate detailed repertoire recommendations. "
                f"Currently limited to {len(analyses)} game(s)."
            )

        for rec in recs:
            lines += [rec, ""]
