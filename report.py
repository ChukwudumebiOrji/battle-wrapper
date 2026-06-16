from database import GameDatabase

class LearningInsights:
    def __init__(self, db: GameDatabase):
        self.db = db

    def generate_report(self, output_path: str):
        """Compiles comprehensive timeline tracking logs of all tactical and positional changes."""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("================================================================================\n")
            f.write("                 COMBINED ARENA BATTLE & LEARNING INSIGHTS                      \n")
            f.write("================================================================================\n\n")
            f.write(self._section_tactical_motifs())
            f.write(self._section_positional_weaknesses())
        print(f"[+] Pattern analysis diagnostic report written to: {output_path}")

    def _section_tactical_motifs(self) -> str:
        motifs = self.db.cursor.execute("""
            SELECT DISTINCT primary_motif FROM move_analysis 
            WHERE primary_motif != 'None' ORDER BY primary_motif ASC
        """).fetchall()

        if not motifs:
            return "🎯 NO TACTICAL BLINDSPOTS CAPTURED IN CURRENT FILTER HORIZONS\n\n"

        text = "🎯 IDENTIFIED TACTICAL BLINDSPOTS & UNRESTRICTED TIMELINE\n" + "-" * 80 + "\n"
        for (motif_name,) in motifs:
            text += f"\n▶ Motif Type: {motif_name}\n"
            instances = self.db.cursor.execute("""
                SELECT m.game_id, m.move_number, m.side, m.move, g.white, g.black, m.eval_loss
                FROM move_analysis m
                JOIN games g ON m.game_id = g.game_id
                WHERE m.primary_motif = ?
                ORDER BY m.game_id ASC, m.move_number ASC
            """, (motif_name,)).fetchall()
            
            for g_id, m_num, side, mv, white, black, loss in instances:
                player = white if side == "white" else black
                text += f"   ↳ On Game #{g_id} at move {m_num}, player '{player}' played '{mv}' [Evaluation Delta: -{loss:.2f} CP]\n"
        return text + "\n"

    def _section_positional_weaknesses(self) -> str:
        ideas = self.db.cursor.execute("""
            SELECT DISTINCT positional_idea FROM move_analysis 
            WHERE positional_idea != 'None' ORDER BY positional_idea ASC
        """).fetchall()

        if not ideas:
            return "♟️ NO ABSTRACT POSITIONAL DRIFT ENCOUNTERED IN REVIEWS\n\n"

        text = "♟️ EXHAUSTIVE STRATEGIC & POSITIONAL INSIGHT TIMELINE\n" + "-" * 80 + "\n"
        for (idea_name,) in ideas:
            text += f"\n▶ Strategic Pattern: {idea_name}\n"
            instances = self.db.cursor.execute("""
                SELECT m.game_id, m.move_number, m.side, m.move, g.white, g.black, m.eval_loss
                FROM move_analysis m
                JOIN games g ON m.game_id = g.game_id
                WHERE m.positional_idea = ?
                ORDER BY m.game_id ASC, m.move_number ASC
            """, (idea_name,)).fetchall()
            
            for g_id, m_num, side, mv, white, black, loss in instances:
                player = white if side == "white" else black
                text += f"   ↳ On Game #{g_id} at move {m_num}, player '{player}' played '{mv}' [Evaluation Delta: -{loss:.2f} CP]\n"
        return text + "\n"