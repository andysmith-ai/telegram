# andysmith-ai/telegram

Post store + CI publisher for the **@andysmith_ai** Telegram channel. Drop a post
in `posts/`; CI publishes it. **What's in the file is what publishes** — no image
logic here.

- Design & handoff: **[DESIGN.md](DESIGN.md)**
- Publisher: [`publish/publish.py`](publish/publish.py) (reconcile vs `posts/<slug>.state.json`)
- Workflow: [`.github/workflows/publish.yml`](.github/workflows/publish.yml)

Setup: repo secret `TELEGRAM_BOT_TOKEN`; repo variable `TG_USERNAME`
(`andysmith_ai`); bot is a channel admin.
