create extension if not exists pg_cron;
create extension if not exists pg_net with schema extensions;
-- The anon key is public by design (it also ships in the page).
select cron.schedule(
  'parlay-push-check',
  '*/10 * * * *',
  $$ select net.http_post(
       url := 'https://phxacgxbhphnvrbcrbtr.supabase.co/functions/v1/parlay-push',
       headers := '{"Content-Type": "application/json", "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBoeGFjZ3hiaHBobnZyYmNyYnRyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAyODYzODcsImV4cCI6MjEwNTg2MjM4N30.UnG8ZLEwcbTjZ4V2Xhjfvwv7d5A80Tzh11A1xgDjpbU"}'::jsonb,
       body := '{"action": "check"}'::jsonb,
       timeout_milliseconds := 20000) $$
);
