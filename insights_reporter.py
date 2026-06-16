# insights_reporter.py
from collections import defaultdict

class InsightsReporter:
    def __init__(self, db_connection):
        """
        Pass the active SQLite database connection object from your wrapper.
        """
        self.conn = db_connection

    def generate_report(self, output_filepath="arena_insights.txt"):
        cursor = self.conn.cursor()
        
        # 1. Fetch data from SQLite, filtering out skipped sections
        cursor.execute("""
            SELECT motif, player_side, uci_move, eval_loss, game_id, move_num 
            FROM move_analysis 
            WHERE motif != 'None' AND positional_idea != 'Game Decided (Skipped)'
        """)
        rows = cursor.fetchall()

        # 2. Group identical behaviors using nested dictionaries
        pattern_agg = defaultdict(lambda: defaultdict(list))
        for motif, side, move, loss, game_id, move_num in rows:
            # STRICT FILTER: Completely drop flat evaluation lines (0.00 CP)
            if float(loss) == 0.00:
                continue
                
            signature = f"Player '{side.upper()}' played '{move}'"
            pattern_agg[motif][signature].append((game_id, move_num, loss))

        # 3. Write dense, condensed summary to file
        with open(output_filepath, "w", encoding="utf-8") as f:
            f.write("="*90 + "\n")
            f.write("                       CONDENSED ARENA INSIGHTS REPORT                         \n")
            f.write("="*90 + "\n\n")

            for motif, signatures in pattern_agg.items():
                f.write(f"▶ Motif Category: {motif}\n")
                f.write("-" * 60 + "\n")
                
                for sig, occurrences in signatures.items():
                    total_times = len(occurrences)
                    avg_loss = sum(occ[2] for occ in occurrences) / total_times
                    
                    # Uncapped single-line citation list 
                    all_citations = ", ".join([f"G#{g_id} (m.{m_num})" for g_id, m_num, _ in occurrences])
                    
                    f.write(f"  ↳ {sig} ➔ Occurred {total_times}x | Avg Loss: {avg_loss:.2f} CP\n")
                    f.write(f"    [All Occurrences: {all_citations}]\n")
                    
                f.write("\n")
        
        print(f"✅ Cleaned report successfully written to {output_filepath}")