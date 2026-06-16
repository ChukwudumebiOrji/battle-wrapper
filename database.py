import sqlite3
import pathlib

class GameDatabase:
    def __init__(self, db_path="chess_analysis.db"):
        self.db_path = pathlib.Path(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self._init_schema()

    def _init_schema(self):
        """Initializes database tables with structural pattern architecture."""
        self.cursor.executescript("""
            CREATE TABLE IF NOT EXISTS games (
                game_id INTEGER PRIMARY KEY AUTOINCREMENT,
                white TEXT,
                black TEXT,
                date TEXT,
                result TEXT,
                pgn_text TEXT UNIQUE
            );

            CREATE TABLE IF NOT EXISTS move_analysis (
                move_id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER,
                move_number INTEGER,
                side TEXT,
                move TEXT,
                eval_loss REAL,
                blunder INTEGER,
                mistake INTEGER,
                inaccuracy INTEGER,
                primary_motif TEXT,
                positional_idea TEXT,
                FOREIGN KEY(game_id) REFERENCES games(game_id)
            );

            CREATE INDEX IF NOT EXISTS idx_move_motif ON move_analysis(primary_motif);
            CREATE INDEX IF NOT EXISTS idx_move_positional ON move_analysis(positional_idea);
        """)
        self.conn.commit()

    def clear_database(self):
        """Clears all game and move analysis data from the database."""
        self.cursor.executescript("""
            DELETE FROM move_analysis;
            DELETE FROM games;
        """)
        self.conn.commit()

    def store_game(self, white, black, date, result, pgn_text) -> int:
        """Stores a game or returns its ID if it was already indexed."""
        try:
            self.cursor.execute("""
                INSERT INTO games (white, black, date, result, pgn_text)
                VALUES (?, ?, ?, ?, ?)
            """, (white, black, date, result, pgn_text))
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.IntegrityError:
            self.cursor.execute("SELECT game_id FROM games WHERE pgn_text = ?", (pgn_text,))
            row = self.cursor.fetchone()
            return row[0] if row else 0

    def store_move_analysis(self, game_id, move_num, side, move_str, eval_loss, blunder, mistake, inaccuracy, motif, positional_idea):
        """Logs an unrestricted positional/tactical snapshot trace."""
        self.cursor.execute("""
            INSERT INTO move_analysis (
                game_id, move_number, side, move, eval_loss, 
                blunder, mistake, inaccuracy, primary_motif, positional_idea
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (game_id, move_num, side, move_str, eval_loss, blunder, mistake, inaccuracy, motif, positional_idea))
        self.conn.commit()

    def close(self):
        self.conn.close()
