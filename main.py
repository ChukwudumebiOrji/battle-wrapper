import argparse, datetime, pathlib, shutil, subprocess, sys
from repertoire_analyzer import RepertoireAnalyzer


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Play games then generate opening repertoire report")
    p.add_argument("--games", type=int, default=5)
    p.add_argument("--depth", type=int, default=10)
    p.add_argument("--analysis-depth", type=int, default=15)
    p.add_argument("--pgn", type=pathlib.Path, required=True, help="Opening PGN for Cutechess")
    return p.parse_args()


def get_cutechess_cli() -> str:
    """Find cutechess-cli in PATH or at standard location"""
    # Try PATH first
    cli = shutil.which("cutechess-cli")
    if cli:
        return cli
    
    # Try macOS homebrew location
    homebrew_cli = pathlib.Path("/opt/homebrew/bin/cutechess-cli")
    if homebrew_cli.exists():
        return str(homebrew_cli)
    
    # Try Downloads location (macOS)
    downloads_cli = pathlib.Path.home() / "Downloads" / "cutechess-1.4.0" / "build" / "cutechess-cli"
    if downloads_cli.exists():
        return str(downloads_cli)
    
    raise FileNotFoundError(
        "cutechess-cli not found. Please install it or add it to PATH.\n"
        "Expected locations checked:\n"
        f"  - {homebrew_cli}\n"
        f"  - {downloads_cli}\n"
        "  - PATH environment variable"
    )


def get_stockfish() -> str:
    """Find stockfish in PATH or at standard location"""
    # Try PATH first
    sf = shutil.which("stockfish")
    if sf:
        return sf
    
    # Try macOS homebrew location
    homebrew_sf = pathlib.Path("/opt/homebrew/bin/stockfish")
    if homebrew_sf.exists():
        return str(homebrew_sf)
    
    # Try Downloads location (macOS)
    downloads_sf = pathlib.Path.home() / "Downloads" / "cutechess-1.4.0" / "stockfish-15.1" / "src" / "stockfish"
    if downloads_sf.exists():
        return str(downloads_sf)
    
    raise FileNotFoundError(
        "stockfish not found. Please install it or add it to PATH.\n"
        "Expected locations checked:\n"
        f"  - {homebrew_sf}\n"
        f"  - {downloads_sf}\n"
        "  - PATH environment variable"
    )


def run_cutechess(args: argparse.Namespace) -> pathlib.Path:
    cli = get_cutechess_cli()
    sf = get_stockfish()
    ts, opening = datetime.datetime.now().strftime("%d-%m_%H-%M"), args.pgn.stem
    out_dir = pathlib.Path(__file__).parent / "engine_battles"; out_dir.mkdir(exist_ok=True)
    out_pgn = out_dir / f"{opening}-{ts}-{args.games}-games.pgn"
    cmd = [
        cli, "-engine", f"cmd={sf}", "name=STOCKFISH", "proto=uci",
        "-engine", f"cmd={sf}", "name=STOCKFISH2", "proto=uci",
        "-each", f"depth={args.depth}", "tc=inf", "-games", str(args.games), "-repeat", "-recover",
        "-openings", f"file={args.pgn.resolve()}", "format=pgn", "order=random", "-pgnout", str(out_pgn),
    ]
    print(f"[INFO] Executing Cutechess Arena: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    return out_pgn


def main() -> None:
    try:
        args = parse_args(); pgn_path = run_cutechess(args)
        print(f"[*] Analyzing middlegame positions from {args.games} games...")
        report = RepertoireAnalyzer(pgn_path, args.pgn.stem, analysis_depth=args.analysis_depth).analyze_and_report(pathlib.Path(__file__).parent / "reports")
        print(f"[+] Generated: {report}"); print("✅ Done")
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr); sys.exit(1)


if __name__ == "__main__": main()
