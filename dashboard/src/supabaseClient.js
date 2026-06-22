import { createClient } from '@supabase/supabase-js'

// The anon key is public by design (RLS gates access). Configure via .env
// (VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY); fall back to the project's
// public values so the dashboard works out of the box.
const supabaseUrl =
  import.meta.env.VITE_SUPABASE_URL || 'https://nfmxwnuvbrozueedkwzo.supabase.co'
const supabaseAnonKey =
  import.meta.env.VITE_SUPABASE_ANON_KEY ||
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5mbXh3bnV2YnJvenVlZWRrd3pvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODE4NzIxODMsImV4cCI6MjA5NzQ0ODE4M30.BinSATN_WLSjHMzBZsZp5IeJ0-kVixND0cjVYYwgsUw'

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
