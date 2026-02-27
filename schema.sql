CREATE TABLE IF NOT EXISTS games (
  id SERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  rows INT NOT NULL,
  cols INT NOT NULL,
  starting_color TEXT NOT NULL CHECK (starting_color IN ('R','Y')),

  status TEXT NOT NULL CHECK (status IN ('IN_PROGRESS','FINISHED')),
  winner TEXT NULL CHECK (winner IN ('R','Y')),
  draw BOOLEAN NOT NULL DEFAULT FALSE,

  original_sequence TEXT NOT NULL DEFAULT '',
  canonical_key TEXT NOT NULL DEFAULT '',

  source_filename TEXT NULL
);

CREATE TABLE IF NOT EXISTS moves (
  id SERIAL PRIMARY KEY,
  game_id INT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  ply INT NOT NULL,
  col INT NOT NULL,
  row INT NOT NULL,
  color TEXT NOT NULL CHECK (color IN ('R','Y'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_game_canonical
ON games(rows, cols, starting_color, canonical_key);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_move_ply
ON moves(game_id, ply);

CREATE INDEX IF NOT EXISTS idx_moves_game
ON moves(game_id);
