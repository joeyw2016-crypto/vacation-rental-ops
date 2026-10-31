#!/bin/bash
# restart.sh - one-click restart for the vacation rental ops Telegram bot
# Usage: ./restart.sh

cd "$(dirname "$0")"

# Stop the old bot process
pkill -f "python3 bot.py" 2>/dev/null
sleep 1

# Start a new one in the background (log goes to bot.log)
nohup python3 bot.py > bot.log 2>&1 &

sleep 2

if pgrep -f "python3 bot.py" > /dev/null; then
  echo "Bot restarted successfully. PID: $(pgrep -f 'python3 bot.py' | head -1)"
  echo "Log tail:"
  tail -3 bot.log
else
  echo "FAILED to start bot. Check bot.log:"
  cat bot.log
fi
