#!/bin/bash
set -euo pipefail

TOKEN=${1:-}
if [[ -z "$TOKEN" ]]; then
  TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' ~/.hermes/.env | cut -d= -f2- | tr -d '\r')
fi

if [[ -z "$TOKEN" ]]; then
  echo "No TOKEN in ~/.hermes/.env"
  exit 1
fi

# Poll latest Voice
UPDATES=$(curl -s "https://api.telegram.org/bot$TOKEN/getUpdates?offset=-1&limit=1" | jq -r '.result[0].message // empty')
if [[ "$UPDATES" == "null" || "$UPDATES" == "empty" ]]; then
  echo "No new messages"
  exit 0
fi

VOICE=$(echo "$UPDATES" | jq -r '.voice.file_id // empty')
CHAT_ID=$(echo "$UPDATES" | jq -r '.chat.id')
if [[ "$VOICE" == "null" || "$VOICE" == "empty" ]]; then
  echo "No voice message"
  exit 0
fi

echo "Voice: $CHAT_ID / $VOICE"

# Download
FILE_PATH=$(curl -s "https://api.telegram.org/bot$TOKEN/getFile?file_id=$VOICE" | jq -r '.result.file_path')
AUDIO_URL="https://api.telegram.org/file/bot$TOKEN/$FILE_PATH"
AUDIO_PATH="/tmp/tg_voice_${VOICE:0:10}.ogg"
curl -s "$AUDIO_URL" -o "$AUDIO_PATH"

# STT
faster-whisper "$AUDIO_PATH" --model base --language de --output_dir /tmp/ --output_format txt

TRANSCRIPT=$(cat "/tmp/${VOICE:0:10}.txt" 2>/dev/null || echo "STT failed")
rm -f "/tmp/${VOICE:0:10}."*

# Send back
curl -s -X POST "https://api.telegram.org/bot$TOKEN/sendMessage" \
  -d chat_id="$CHAT_ID" \
  -d text="STT Transcript: $TRANSCRIPT" >/dev/null

# Cleanup
rm "$AUDIO_PATH"
echo "Transcript: $TRANSCRIPT (sent to $CHAT_ID)"
