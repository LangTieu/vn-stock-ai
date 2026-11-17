CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  folder TEXT NOT NULL CHECK (folder IN ('inbox', 'sent')),
  message_id TEXT,
  in_reply_to TEXT,
  references_hdr TEXT,
  envelope_from TEXT,
  envelope_to TEXT,
  from_addr TEXT NOT NULL DEFAULT '',
  from_name TEXT NOT NULL DEFAULT '',
  to_addrs TEXT NOT NULL DEFAULT '[]',
  cc_addrs TEXT NOT NULL DEFAULT '[]',
  reply_to TEXT,
  subject TEXT NOT NULL DEFAULT '',
  snippet TEXT NOT NULL DEFAULT '',
  text_body TEXT NOT NULL DEFAULT '',
  html_body TEXT,
  date INTEGER NOT NULL,
  is_read INTEGER NOT NULL DEFAULT 0,
  raw_key TEXT,
  size INTEGER NOT NULL DEFAULT 0,
  attachments TEXT NOT NULL DEFAULT '[]',
  resend_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_folder_date ON messages (folder, date DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_folder_msgid
  ON messages (folder, message_id) WHERE message_id IS NOT NULL;
