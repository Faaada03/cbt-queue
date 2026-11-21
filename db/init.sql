CREATE TABLE IF NOT EXISTS answer_keys (
  exam_id TEXT,
  soal_no INT,
  jawaban TEXT,
  PRIMARY KEY (exam_id, soal_no)
);

CREATE TABLE IF NOT EXISTS submissions (
  student_id TEXT,
  exam_id TEXT,
  answers JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'diterima',
  received_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (student_id, exam_id)
);

CREATE TABLE IF NOT EXISTS results (
  student_id TEXT,
  exam_id TEXT,
  score NUMERIC(5,2),
  graded_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (student_id, exam_id)
);

INSERT INTO answer_keys VALUES
  ('UJIAN-01', 1, 'A'),
  ('UJIAN-01', 2, 'B'),
  ('UJIAN-01', 3, 'C'),
  ('UJIAN-01', 4, 'D'),
  ('UJIAN-01', 5, 'A')
ON CONFLICT (exam_id, soal_no) DO NOTHING;