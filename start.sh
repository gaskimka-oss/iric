#!/usr/bin/env bash
# Точка входа для хостинга
set -e
pip install --no-cache-dir -r requirements.txt
exec python bot.py
