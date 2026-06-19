import { createClient } from '@supabase/supabase-js'

const supabaseUrl = 'https://nfmxwnuvbrozueedkwzo.supabase.co'
const supabaseAnonKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5mbXh3bnV2YnJvenVlZWRrd3pvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODE4NzIxODMsImV4cCI6MjA5NzQ0ODE4M30.BinSATN_WLSjHMzBZsZp5IeJ0-kVixND0cjVYYwgsUw'

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
