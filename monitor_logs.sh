#!/bin/bash
echo "Monitoring Beast Engine Logs..."
echo "Use Ctrl+C to exit."
docker exec -it beast_engine tail -f /app/logs/beast_engine.log
