import argparse
import pathlib
import subprocess
import shutil
import datetime

# --- Setup Paths ---
home = pathlib.Path.home()
cutechess = home / "Downloads/cutechess-1.4.0"
CUTECHESS_PATH = cutechess / "build" / "cutechess-cli"
SYZYGY_PATH = cutechess / "Syzygy"
VIRIDITHAS_PATH = cutechess / "viridithas/target/release/viridithas"
STOCKFISH_PATH = cutechess / "stockfish-15.1/src/stockfish"
CURRENT_DIR = pathlib.Path(__file__).parent.resolve()
OUTPUT_DIR = CURRENT_DIR / "engine_battles"
OUTPUT_DIR.mkdir(exist_ok=True)


def get_args():
    parser = argparse.ArgumentParser(description="The Ultimate Engine Battle Script")
    parser.add_argument("--pgn", help="Path to the opening PGN file")
    parser.add_argument(
        "--use-fen", type=str, help="Starting position in FEN format", default=None
    )
    parser.add_argument(
        "--fen-file",
        type=str,
        help="Path to a file containing a list of FENs/EPDs",
        default=None,
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--ava", action="store_true")
    mode.add_argument("--1vx", dest="mode_1vx", metavar="CHALLENGER")
    mode.add_argument("--1v1", dest="mode_1v1", nargs=2, metavar=("ENG1", "ENG2"))

    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--tc", type=str, default="inf")
    parser.add_argument("--st", type=int)
    parser.add_argument("--depth", type=int, default=24)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--hash", type=int, default=128)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--repeat", action="store_true")
    parser.add_argument("--multi-pv", type=int, default=1)

    # Asymmetric Overrides
    parser.add_argument("--w-tc", type=str)
    parser.add_argument("--w-st", type=int)
    parser.add_argument("--w-depth", type=int)
    parser.add_argument("--b-tc", type=str)
    parser.add_argument("--b-st", type=int)
    parser.add_argument("--b-depth", type=int)

    return parser.parse_args()


# --- Engine Configs ---
def config_stockfish(args):
    path = STOCKFISH_PATH
    # print(f"Checking Stockfish at: {path}")

    if not path.exists():
        # Fallback to check if it's in the PATH
        path = shutil.which("stockfish")
        # print(f"Checking Stockfish at: {path}")
        if not path:
            raise FileNotFoundError(f"Stockfish not found at {path} or in PATH")

    # Build engine config with specified options, ensuring Syzygy path is included if available
    cfg = ["-engine", f"cmd={path}", "name=STOCKFISH", "proto=uci"]
    cfg.append(f"option.Threads={args.threads}")
    cfg.append(f"option.Hash={args.hash}")
    if SYZYGY_PATH.exists():
        cfg.append(f"option.SyzygyPath={SYZYGY_PATH}")
        # print(f"Syzygy path set to: {SYZYGY_PATH}")
    return cfg


def config_viridithas(args):
    path = VIRIDITHAS_PATH
    # print(f"Checking Viridithas at: {path}")
    if not path.exists():
        # Fallback to check if it's in the PATH
        path = shutil.which("viridithas")
        # print(f"Checking Viridithas at: {path}")
        if not path:
            raise FileNotFoundError(f"Viridithas not found at {path} or in PATH")

    # Build engine config with specified options, ensuring Syzygy path is included if available
    cfg = ["-engine", f"cmd={path}", "name=VIRIDITHAS", "proto=uci"]
    cfg.append(f"option.Threads={args.threads}")
    cfg.append(f"option.Hash={args.hash}")
    if SYZYGY_PATH.exists():
        cfg.append(f"option.SyzygyPath={SYZYGY_PATH}")
        # print(f"Syzygy path set to: {SYZYGY_PATH}")
    return cfg


def run_battle():
    args = get_args()
    dispatch = {"stockfish": config_stockfish, "viridithas": config_viridithas}

    if args.mode_1v1:
        engine_names = args.mode_1v1
    else:
        engine_names = ["stockfish", "viridithas"]

    # 1. Base Binary
    cmd = [str(CUTECHESS_PATH)]

    # 2. Engine Definitions
    for i, name in enumerate(engine_names):
        e_name = name.lower()

        try:
            e_cfg = dispatch[e_name](args)
        except KeyError:
            e_path = shutil.which(e_name)
            if not e_path:
                raise FileNotFoundError(f"Engine '{e_name}' not found in your PATH")
            e_cfg = ["-engine", f"cmd={e_path}", f"name={name.upper()}", "proto=uci"]

        # Preserve MultiPV logic
        if "stockfish" in e_name and args.multi_pv > 1:
            e_cfg.append(f"option.MultiPV={args.multi_pv}")

        cmd.extend(e_cfg)

    # 3. Build -each time control flags, supporting asymmetric if specified
    each_flags = []

    # Check for full side overrides, fallback to common, otherwise nothing
    # White:
    if args.w_depth:
        each_flags.append(f"depth={args.w_depth}")
    elif args.w_st:
        each_flags.append(f"st={args.w_st}")
    elif args.w_tc:
        each_flags.append(f"tc={args.w_tc}")

    # Black:
    if args.b_depth:
        each_flags.append(f"depth={args.b_depth}")
    elif args.b_st:
        each_flags.append(f"st={args.b_st}")
    elif args.b_tc:
        each_flags.append(f"tc={args.b_tc}")

    # If no overrides, use common
    if not each_flags:
        if args.depth:
            each_flags.append(f"depth={args.depth}")
        elif args.st:
            each_flags.append(f"st={args.st}")
        else:
            each_flags.append(f"tc={args.tc}")

    if (any("depth=" in f or "st=" in f for f in each_flags)) and not any(
        "tc=" in f for f in each_flags
    ):
        each_flags.append("tc=inf")

    cmd.extend(["-each"] + each_flags)

    # 4. Global Match Settings
    timestamp = datetime.datetime.now().strftime("%d-%m_%H-%M")
    opening_name = pathlib.Path(args.pgn or "position").stem
    output_filename = OUTPUT_DIR / f"{opening_name}-{timestamp}-{args.games}-games.pgn"

    cmd.extend(
        [
            "-tournament",  # Use tournament mode to ensure proper scorekeeping and PGN output
            "gauntlet",
            "-games",  # Number of games to play (will be doubled if --repeat is used)
            str(args.games),
            "-concurrency",  # Number of concurrent games to run
            str(args.concurrency),
            "-repeat"
            if args.repeat
            else "",  # Repeat games with swapped colors to balance out first-move advantage
            "-recover",  # Allow recovery from crashes without losing all progress
            "-draw",  # Enforce draw conditions to avoid infinite moves
            "movenumber=40",
            "movecount=3",
            "score=150",
            "-resign",  # Enforce resignation to avoid infinite moves
            "movecount=5",
            "score=400",
            "-pgnout",  # Output PGN with full move details, including time and depth annotations
            str(output_filename),
        ]
    )

    # 5. Opening Settings (Preserving PGN and FEN flags)
    if args.pgn:
        pgn_path = pathlib.Path(args.pgn).resolve()
        cmd.extend(
            ["-openings", f"file={pgn_path}", "format=pgn", "order=random"]
        )  # Randomize opening selection from PGN to ensure variety across games
    elif args.use_fen:
        temp_epd = pathlib.Path("current_start.epd")
        temp_epd.write_text(args.use_fen.strip())
        cmd.extend(
            ["-openings", f"file={temp_epd.resolve()}", "format=epd"]
        )  # Use EPD format for single FEN to ensure proper parsing, even if it means creating a temporary file
    elif args.fen_file:
        fen_path = pathlib.Path(args.fen_file).resolve()
        cmd.extend(
            ["-openings", f"file={fen_path}", "format=epd", "order=random"]
        )  # Randomize opening selection from FEN file to ensure variety across games

    # 6. Clean and Execute
    cmd = [str(c) for c in cmd if c]
    # print("[DEBUG] Final command:")
    # print(" ".join(cmd))
    subprocess.run(cmd)


if __name__ == "__main__":
    run_battle()
