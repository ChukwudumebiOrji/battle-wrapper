import argparse, datetime, pathlib, shutil, subprocess, sys
from repertoire_analyzer import RepertoireAnalyzer


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Play games then generate opening repertoire report")
    p.add_argument("--1v1", dest="engines", nargs=2, metavar=("WHITE", "BLACK"), required=True)
    p.add_argument("--games", type=int, default=5)
    p.add_argument("--depth", type=int, default=10)
    p.add_argument("--analysis-depth", type=int, default=15)
    p.add_argument("--pgn", type=pathlib.Path, required=True, help="Opening PGN for Cutechess")
    return p.parse_args()


def run_cutechess(args: argparse.Namespace) -> pathlib.Path:
    cli = shutil.which("cutechess-cli")
    if not cli: raise FileNotFoundError("cutechess-cli not found in PATH")
    ts, opening = datetime.datetime.now().strftime("%d-%m_%H-%M"), args.pgn.stem
    out_dir = pathlib.Path(__file__).parent / "engine_battles"; out_dir.mkdir(exist_ok=True)
    out_pgn = out_dir / f"{opening}-{ts}-{args.games}-games.pgn"
    cmd = [
        cli, "-engine", f"cmd={args.engines[0]}", f"name={args.engines[0].upper()}", "proto=uci",
        "-engine", f"cmd={args.engines[1]}", f"name={args.engines[1].upper()}", "proto=uci",
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
