#!/bin/bash
cd "$(dirname "$0")"
AI_BRIDGE_ROOT="$PWD/ArchiveWorkbenchData/Settings/archive-workbench-ai-bridge"
AI_EXECUTABLE="${ARCHIVE_WORKBENCH_AI_EXECUTABLE:-}"
if [ -n "$AI_EXECUTABLE" ] && [ -x "$AI_EXECUTABLE" ]; then
  "$AI_EXECUTABLE" bridge stop --root "$AI_BRIDGE_ROOT" >/dev/null 2>&1 || true
elif command -v aw-ai >/dev/null 2>&1; then
  aw-ai bridge stop --root "$AI_BRIDGE_ROOT" >/dev/null 2>&1 || true
fi
docker compose --profile cpu --profile gpu down
