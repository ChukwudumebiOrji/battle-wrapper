import argparse
import pathlib
import subprocess
import shutil
import datetime
import sys
import io
import chess.pgn
from dataclasses import dataclass
from typing import Optional, List
from enum import Enum
import sqlite3

# Import cross-module sibling components
from database import GameDatabase
from engine import AnalysisCore
from report import LearningInsights
from insights_reporter import InsightsReporter

# --- CUTECHESS ARENA ORCHESTRATION LAYER ---

class TimeControl(Enum):
    BLITZ = "tc"
    DEPTH = "depth"
    MOVETIME = "st"

@dataclass
class EngineConfig:
    name: str
    path: pathlib.Path
    threads: int
    hash: int
    syzygy_path: Optional[pathlib.Path] = None
    multi_pv: int = 1

    def validate(self) -> None:
        if not self.path.exists():
            fallback = shutil.which(self.name.lower())
            if fallback:
                self.path = pathlib.Path(fallback)
            else:
                raise FileNotFoundError(f"Engine '{self.name}' not found at {self.path} or in PATH")
                
    def to_cutechess_args(self) -> List[str]:
        cfg = [
            "-engine", f"cmd={self.path}", f"name={self.name.upper()}", "proto=uci",
            f"option.Threads={self.threads}", f"option.Hash={self.hash}",
        ]
        if self.syzygy_path and self.syzygy_path.exists():
            cfg.append(f"option.SyzygyPath={self.syzygy_path}")
        if self.name.lower() == "stockfish" and self.multi_pv > 1:
            cfg.append(f"option.MultiPV={self.multi_pv}")
        return cfg

@dataclass
class TimeControlConfig:
    tc: Optional[str] = None
    st: Optional[int] = None
    depth: Optional[int] = None
    
    def to_cutechess_arg(self) -> str:
        if self.depth is not None: return f"depth={self.depth}"
        elif self.st is not None: return f"st={self.st / 1000}"
        else: return f"tc={self.tc or 'inf'}"

class PathManager:
    def __init__(self):
        self.home = pathlib.Path.home()
        self.cutechess_root = self.home / "Downloads" / "cutechess-1.4.0"
        self.cutechess_cli = self.cutechess_root / "build" / "cutechess-cli"
        self.syzygy = self.cutechess_root / "Syzygy"
        self.viridithas = self.cutechess_root / "viridithas" / "target" / "release" / "viridithas"
        self.stockfish = self.cutechess_root / "stockfish-15.1" / "src" / "stockfish"
        self.script_dir = pathlib.Path(__file__).parent.resolve()
        self.output_dir = self.script_dir / "engine_battles"
        self.output_dir.mkdir(exist_ok=True)
    
    def validate_cutechess(self) -> None:
        if not self.cutechess_cli.exists():
            fallback = shutil.which("cutechess-cli")
            if fallback: self.cutechess_cli = pathlib.Path(fallback)
            else: raise FileNotFoundError(f"cutechess-cli not found at {self.cutechess_cli} or in PATH")
    
    def get_engine_path(self, engine_name: str) -> Optional[pathlib.Path]:
        engines = { "stockfish": self.stockfish, "viridithas": self.viridithas }
        return engines.get(engine_name.lower())

class BattleScriptArgs:
    @staticmethod
    def parse() -> argparse.Namespace:
        parser = argparse.ArgumentParser(description="Ultimate Engine Battle & Deep Analysis Core Pipeline")
        
        # Opening adjustments
        opening_group = parser.add_mutually_exclusive_group()
        opening_group.add_argument("--pgn", type=pathlib.Path, help="Path to opening book/source PGN file")
        opening_group.add_argument("--use-fen", type=str, help="Starting position FEN string")
        opening_group.add_argument("--fen-file", type=pathlib.Path, help="Path to file containing FENs/EPDs")
        
        # Match layouts
        mode_group = parser.add_mutually_exclusive_group(required=True)
        mode_group.add_argument("--ava", action="store_true", help="All vs All mode")
        mode_group.add_argument("--1vx", dest="mode_1vx", metavar="CHALLENGER", help="One vs many mode")
        mode_group.add_argument("--1v1", dest="mode_1v1", nargs=2, metavar=("ENG1", "ENG2"), help="One vs one mode")
        
        # Standard configuration rules
        parser.add_argument("--games", type=int, default=1, help="Number of games")
        parser.add_argument("--tc", type=str, help="Time control (e.g., 5+0.1)")
        parser.add_argument("--st", type=int, help="Move time in milliseconds")
        parser.add_argument("--depth", type=int, help="Search depth limit")
        parser.add_argument("--threads", type=int, default=1, help="Engine threads")
        parser.add_argument("--hash", type=int, default=128, help="Hash size in MB")
        parser.add_argument("--concurrency", type=int, default=1, help="Concurrent arenas")
        parser.add_argument("--repeat", action="store_true", help="Repeat with colors swapped")
        parser.add_argument("--multi-pv", type=int, default=1, help="MultiPV for Stockfish")
        
        # Mining specific configuration overrides
        parser.add_argument("--report", default="performance_report.txt", help="Output file path for text report")
        parser.add_argument("--db", default="chess_analysis.db", help="Path to sqlite analysis data file")
        parser.add_argument("--analysis-depth", type=int, default=20, help="Engine depth used for post-game data mining")
        parser.add_argument("--browse", action="store_true", help="Launch interactive evaluation summary browser")
        
        # Asymmetric rulesets
        parser.add_argument("--w-tc", type=str, help="White time control")
        parser.add_argument("--w-st", type=int, help="White move time")
        parser.add_argument("--w-depth", type=int, help="White search depth")
        parser.add_argument("--b-tc", type=str, help="Black time control")
        parser.add_argument("--b-st", type=int, help="Black move time")
        parser.add_argument("--b-depth", type=int, help="Black search depth")
        
        return parser.parse_args()

    @staticmethod
    def validate(args: argparse.Namespace) -> None:
        tc_args = [args.tc, args.st, args.depth]
        if sum(1 for x in tc_args if x is not None) > 1:
            raise ValueError("Cannot combine --tc, --st, and --depth parameters.")
        if not any(tc_args) and not any([args.w_tc, args.w_st, args.w_depth, args.b_tc, args.b_st, args.b_depth]):
            args.depth = 24

class BattleCommand:
    def __init__(self, paths: PathManager, args: argparse.Namespace, engines: List[EngineConfig]):
        self.paths = paths
        self.args = args
        self.engines = engines
        self.cmd: List[str] = []
        self._temp_files: List[pathlib.Path] = []
        self.output_pgn: Optional[pathlib.Path] = None
            
    def build(self) -> List[str]:
        self.cmd = []
        self._add_executable()
        self._add_engines()
        self._add_time_controls()
        self._add_match_settings()
        self._add_openings()
        return [str(c) for c in self.cmd if c]
    
    def _add_executable(self) -> None:
        self.paths.validate_cutechess()
        self.cmd.append(str(self.paths.cutechess_cli))
    
    def _add_engines(self) -> None:
        for engine in self.engines:
            engine.validate()
            self.cmd.extend(engine.to_cutechess_args())
    
    def _add_time_controls(self) -> None:
        white_tc = TimeControlConfig(tc=self.args.w_tc, st=self.args.w_st, depth=self.args.w_depth)
        black_tc = TimeControlConfig(tc=self.args.b_tc, st=self.args.b_st, depth=self.args.b_depth)
        has_w = any([self.args.w_tc, self.args.w_st, self.args.w_depth])
        has_b = any([self.args.b_tc, self.args.b_st, self.args.b_depth])

        if has_w or has_b:
            common = TimeControlConfig(tc=self.args.tc, st=self.args.st, depth=self.args.depth)
            w_arg = white_tc.to_cutechess_arg() if has_w else common.to_cutechess_arg()
            b_arg = black_tc.to_cutechess_arg() if has_b else common.to_cutechess_arg()
            self.cmd.extend(["-each", w_arg, b_arg])
        else:
            common_tc = TimeControlConfig(tc=self.args.tc, st=self.args.st, depth=self.args.depth)
            self.cmd.extend(["-each", common_tc.to_cutechess_arg()])
            if self.args.depth is not None or self.args.st is not None:
                self.cmd.append("tc=inf")
    
    def _add_match_settings(self) -> None:
        timestamp = datetime.datetime.now().strftime("%d-%m_%H-%M")
        opening_name = (pathlib.Path(self.args.pgn or "position").stem if self.args.pgn else "position")
        self.output_pgn = self.paths.output_dir / f"{opening_name}-{timestamp}-{self.args.games}-games.pgn"
        
        self.cmd.extend([
            "-tournament", "gauntlet", "-games", str(self.args.games),
            "-concurrency", str(self.args.concurrency), "-recover",
            "-draw", "movenumber=40", "movecount=3", "score=150",
            "-resign", "movecount=5", "score=400",
            "-pgnout", str(self.output_pgn),
        ])
        if self.args.repeat: self.cmd.append("-repeat")
    
    def _add_openings(self) -> None:
        if self.args.pgn:
            p = self.args.pgn.resolve()
            if not p.exists(): raise FileNotFoundError(f"PGN file not found: {p}")
            self.cmd.extend(["-openings", f"file={p}", "format=pgn", "order=random"])
        elif self.args.use_fen:
            temp_epd = pathlib.Path("current_start.epd")
            temp_epd.write_text(self.args.use_fen.strip())
            self._temp_files.append(temp_epd)
            self.cmd.extend(["-openings", f"file={temp_epd.resolve()}", "format=epd"])
        elif self.args.fen_file:
            p = self.args.fen_file.resolve()
            if not p.exists(): raise FileNotFoundError(f"FEN file not found: {p}")
            self.cmd.extend(["-openings", f"file={p}", "format=epd", "order=random"])
    
    def execute(self) -> Optional[pathlib.Path]:
        cmd = self.build()
        print(f"[INFO] Executing Cutechess Arena: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, check=False)
            if result.returncode != 0:
                print(f"[WARNING] cutechess-cli exited with code {result.returncode}")
            return self.output_pgn
        except FileNotFoundError:
            print("[ERROR] cutechess-cli binary execution failed.", file=sys.stderr)
            return None
        finally:
            self.cleanup()

    def cleanup(self) -> None:
        for f in self._temp_files:
            if f.exists():
                try: f.unlink()
                except OSError: pass

def get_engines_for_mode(args: argparse.Namespace, paths: PathManager) -> List[EngineConfig]:
    if args.mode_1v1: engine_names = args.mode_1v1
    elif args.mode_1vx: engine_names = ["stockfish", args.mode_1vx]
    else: engine_names = ["stockfish", "viridithas"]
        
    engines = []
    for name in engine_names:
        engine_path = paths.get_engine_path(name)
        if not engine_path: engine_path = pathlib.Path(shutil.which(name) or name)
        engines.append(
            EngineConfig(
                name=name, path=engine_path, threads=args.threads,
                hash=args.hash, syzygy_path=paths.syzygy, multi_pv=args.multi_pv,
            )
        )
    return engines

# --- DEEP POST-GAME PATTERN MINING INTERFACE ---

def post_game_mining_pipeline(pgn_file: pathlib.Path, args: argparse.Namespace, db: GameDatabase):
    print(f"\n[*] Commencing thermal-optimized pattern mining on: {pgn_file}")
    if not pgn_file.exists():
        print(f"[-] Target match tracking PGN file missing: {pgn_file}")
        return

    games_to_process = []
    with open(pgn_file, encoding="utf-8") as f:
        while True:
            game = chess.pgn.read_game(f)
            if game is None: break
            games_to_process.append(game)

    print(f"[+] Loaded {len(games_to_process)} arena matches. Launching multi-threaded analyzer...")
    engine_path = "/opt/homebrew/bin/stockfish" if pathlib.Path("/opt/homebrew/bin/stockfish").exists() else "/usr/games/stockfish"
    
    # Thermal Safety Guard: Hand 2 threads to the single active engine instance
    analyzer = AnalysisCore(engine_path=engine_path, depth=args.analysis_depth)
    try:
        analyzer.engine.configure({"Threads": 2, "Hash": 4096})
    except Exception:
        pass

    for idx, game in enumerate(games_to_process, 1):
        white = game.headers.get("White", "Unknown")
        black = game.headers.get("Black", "Unknown")
        date = game.headers.get("Date", "????.??.??")
        result = game.headers.get("Result", "*")
        
        print(f"  [{idx}/{len(games_to_process)}] Processing Patterns: {white} vs {black}")
        game_id = db.store_game(white, black, date, result, str(game))
        
        board = game.board()
        move_num = 1

        # Track whether we should skip heavy analysis for the rest of this game
        short_circuit_triggered = False
        recent_evals = []

        for move in game.mainline_moves():
            side = "white" if board.turn == chess.WHITE else "black"
            
            # If a flag was already triggered, we just quickly push the moves to finish the game 
            # and log them without wasting CPU power on Stockfish evaluations
            if short_circuit_triggered:
                board.push(move)
                db.store_move_analysis(
                    game_id, move_num, side, move.uci(), 0.0,
                    0, 0, 0, "None", "Game Decided (Skipped)"
                )
                if side == "black": move_num += 1
                continue

            # 1. Fetch Current Position Evaluation Prior to Move
            eval_before = analyzer.analyze_position(board)
            
            # 2. ENG-SPECIFIC SHORT-CIRCUIT FLAGS
            # Flag A: Decisive Graveyard Threshold (+/- 2.5)
            if abs(eval_before) >= 2.5:
                print(f"    [➔] Short-circuit: Game evaluation reached decisive graveyard threshold ({eval_before:.2f}). Skipping rest of engine processing.")
                short_circuit_triggered = True
                
            # Track evaluation history to catch flatlines
            recent_evals.append(eval_before)
            if len(recent_evals) > 6:
                recent_evals.pop(0)
                
            # Flag B: Post Move-40 Dead 0.00 Flatline Filter
            if move_num >= 40 and len(recent_evals) == 6 and all(v == 0.00 for v in recent_evals):
                print(f"    [➔] Short-circuit: Dead 0.00 flatline detected after move 40. Skipping remainder of drawing lines.")
                short_circuit_triggered = True

            # 3. Standard Analysis and Logging (Only runs if short_circuit_triggered is still False)
            if not short_circuit_triggered:
                positional_idea = analyzer.detect_positional_idea(board, move)
                board.push(move)
                eval_after = analyzer.analyze_position(board)
                
                eval_loss = max(0.0, eval_before - eval_after) if side == "white" else max(0.0, eval_after - eval_before)
                
                blunder = 1 if eval_loss >= 2.0 else 0
                mistake = 1 if (0.9 <= eval_loss < 2.0) else 0
                inaccuracy = 1 if (0.3 <= eval_loss < 0.9) else 0
                motif = "Tactical Geometry: Missed Fork / Double Attack" if blunder else "None"
                
                db.store_move_analysis(
                    game_id, move_num, side, move.uci(), eval_loss,
                    blunder, mistake, inaccuracy, motif, positional_idea
                )
            else:
                # Catch the specific move that actually crossed the threshold
                board.push(move)
                db.store_move_analysis(
                    game_id, move_num, side, move.uci(), 0.0,
                    0, 0, 0, "None", "Threshold Crossed"
                )

            if side == "black": move_num += 1

    analyzer.close()
    
    # Generate your original performance report
    insights = LearningInsights(db)
    insights.generate_report(args.report)
    
    # Generate the new highly-condensed insights summary (Fix #1 & #3 applied)
    print("[*] Generating condensed arena insights dashboard...")
    try:
        condensed_reporter = InsightsReporter(db.conn)
        condensed_reporter.generate_report("arena_insights.txt")
    except Exception as e:
        print(f"[WARNING] Advanced insight grouping failed: {e}")

def console_loop(db: GameDatabase):
    while True:
        print("\n" + "=" * 40 + "\n   CHESS INTERACTIVE CONSOLE\n" + "=" * 40)
        print("1. Display All Stored Matches\n2. Exit")
        choice = input("\nSelect system execution pathway (1-2): ").strip()
        if choice == "1":
            rows = db.cursor.execute("SELECT game_id, white, black, date, result FROM games").fetchall()
            print("\n--- INDEXED MATCH RECORDS SYSTEM DATABASE ---")
            for r in rows:
                print(f"Match #{r[0]}: [{r[3]}] {r[1]} vs {r[2]} ➔ {r[4]}")
        elif choice == "2":
            break

# --- PIPELINE ENTRY POINT ---

def main() -> None:
    try:
        paths = PathManager()
        args = BattleScriptArgs.parse()
        BattleScriptArgs.validate(args)
        
        # 1. Execute Engine Match Tournament Arena via Cutechess
        engines = get_engines_for_mode(args, paths)
        battle = BattleCommand(paths, args, engines)
        generated_pgn = battle.execute()
        
        # 2. Automated Hand-off to Data Mining Engine 
        if generated_pgn and generated_pgn.exists():
            db = GameDatabase(args.db)
            try:
                post_game_mining_pipeline(generated_pgn, args, db)
                if args.browse:
                    console_loop(db)
            finally:
                db.close()
                
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[INFO] Pipeline execution halted by operator request.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"[ERROR] Unexpected runtime failure: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()