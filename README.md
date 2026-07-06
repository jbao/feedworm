Available commands:
  feedworm import <opml.xml>     # Import from 小宇宙 OPML export
  feedworm add <url>             # Add single podcast
  feedworm list                  # Show subscribed podcasts
  feedworm episodes <id>         # Show episodes for a podcast
  feedworm sync                  # Download new episodes
  feedworm transcribe            # Transcribe downloaded episodes
  feedworm show <episode_id>     # View transcript in terminal
  feedworm open <episode_id>     # Open transcript in editor
  feedworm search "关键词"        # Search all transcripts
  feedworm auto                  # Automated daily job (sync + transcribe)

  To get started:
  1. Get a Groq API key at https://console.groq.com (free tier available)
  2. Export OPML from 小宇宙 app (Settings → Export subscriptions)
  3. Run:
  cd ~/code/github/feedworm
  export GROQ_API_KEY="your-key-here"
  uv run feedworm import ~/path/to/subscriptions.opml
  uv run feedworm sync --limit 1
  uv run feedworm transcribe --limit 1

  Transcripts saved to: ~/.local/share/feedworm/transcripts/

## Launchd

  To activate the schedule

  # Copy plist and load it
  cp com.feedworm.daily.plist ~/Library/LaunchAgents/
  launchctl load ~/Library/LaunchAgents/com.feedworm.daily.plist

  # Test-trigger immediately
  launchctl start com.feedworm.daily

  # Check logs
  tail -f ~/.local/share/feedworm/logs/daily-$(date +%Y-%m-%d).log
