CREATE TABLE public.archive_notes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL DEFAULT auth.uid(),
  chat_id TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.archive_notes TO authenticated;
GRANT ALL ON public.archive_notes TO service_role;
ALTER TABLE public.archive_notes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own notes select" ON public.archive_notes FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "own notes insert" ON public.archive_notes FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "own notes delete" ON public.archive_notes FOR DELETE TO authenticated USING (auth.uid() = user_id);