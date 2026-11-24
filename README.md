# AION 2 timers -> Discord

Draws the AION 2 (Asia server, JST) event schedule as an image from https://shugo.gg/timers.json
and posts / edits one Discord webhook message in place (GitHub Actions, every 10 minutes).
The webhook URL is stored only in the repository secret `DISCORD_WEBHOOK_URL`.
Unofficial data from Shugo.GG; not affiliated with NCSOFT.
