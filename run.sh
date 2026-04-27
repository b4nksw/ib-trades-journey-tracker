#!/bin/bash
set -e
cd "$(dirname "$0")"
mkdir -p logs
exec >> logs/sync.log 2>&1
source venv/bin/activate
python main.py
