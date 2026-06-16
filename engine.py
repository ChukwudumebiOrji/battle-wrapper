import chess
import chess.engine
import pathlib

class AnalysisCore:
    def __init__(self, engine_path="/opt/homebrew/bin/stockfish", depth=20):
        self.engine_path = pathlib.Path(engine_path)
        self.depth = depth
        if not self.engine_path.exists():
            raise FileNotFoundError(f"Analysis engine not found at: {self.engine_path}")
        self.engine = chess.engine.SimpleEngine.popen_uci(str(self.engine_path))

    def analyze_position(self, board: chess.Board) -> float:
        """Evaluates board position returning score in centipawns relative to side-to-move."""
        info = self.engine.analyse(board, chess.engine.Limit(depth=self.depth))
        score = info["score"].relative
        if score.is_mate():
            return 1000.0 if score.mate() > 0 else -1000.0
        return float(score.score()) / 100.0

    def detect_positional_idea(self, board_before: chess.Board, played_move: chess.Move) -> str:
        """Master-tier trend analyzer designed to catch elite positional drift."""
        board_after = board_before.copy()
        board_after.push(played_move)
        turn = board_before.turn

        # --- TREND 1: SPACE & DOMAIN RELINQUISHMENT ---
        enemy_half_squares = (
            chess.SquareSet(chess.BB_RANKS[4] | chess.BB_RANKS[5] | chess.BB_RANKS[6] | chess.BB_RANKS[7])
            if turn == chess.WHITE else
            chess.SquareSet(chess.BB_RANKS[0] | chess.BB_RANKS[1] | chess.BB_RANKS[2] | chess.BB_RANKS[3])
        )
        control_before = sum(1 for sq in enemy_half_squares if board_before.is_attacked_by(turn, sq))
        control_after = sum(1 for sq in enemy_half_squares if board_after.is_attacked_by(turn, sq))
        if (control_before - control_after) > 4:
            return "Elite Trend: Strategic Relinquishment of Territory / Space"

        # --- TREND 2: PAWN-LEVER TENSION LIQUIDATION ---
        p = board_before.piece_at(played_move.from_square)
        if p and p.piece_type == chess.PAWN and board_before.is_capture(played_move):
            if chess.square_file(played_move.to_square) in [2, 3, 4, 5]: # C, D, E, F files
                return "Elite Trend: Faulty Central Pawn Tension Liquidation"

        # --- TREND 3: PROPHYLAXIS FAILURE ---
        board_after.turn = not turn
        opponent_moves = list(board_after.legal_moves)
        board_after.turn = turn
        significant_advancements = 0
        for op_m in opponent_moves:
            p_op = board_after.piece_at(op_m.from_square)
            if p_op and p_op.piece_type == chess.PAWN:
                dest_rank = chess.square_rank(op_m.to_square)
                if (turn == chess.WHITE and dest_rank <= 3) or (turn == chess.BLACK and dest_rank >= 4):
                    significant_advancements += 1
        if significant_advancements > 2:
            return "Elite Trend: Prophylaxis Failure / Allowed Opponent Counter-Expansion"

        # --- TREND 4: MICRO-MOBILITY RESTRICTION ---
        mobility_before = len(list(board_before.legal_moves))
        board_after.turn = turn
        mobility_after = len(list(board_after.legal_moves))
        board_after.turn = not turn
        if (mobility_before - mobility_after) > 8:
            return "Subtle: Severe Restriction of Personal Piece Mobility"

        return "Subtle Positional Drift"

    def close(self):
        self.engine.quit()