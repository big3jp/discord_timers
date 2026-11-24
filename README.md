# AION 2 timers -> Discord

Builds the AION 2 (Asia server, UTC+9) event schedule from https://shugo.gg/timers.json and edits one Discord webhook message in place.
Run by GitHub Actions every 5 minutes. The webhook URL is stored only in the repository secret `DISCORD_WEBHOOK_URL`.
Unofficial data from Shugo.GG; not affiliated with NCSOFT.
