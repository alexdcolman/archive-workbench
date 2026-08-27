#!/bin/bash
cd "$(dirname "$0")"
docker compose --profile cpu --profile gpu down
