#!/bin/sh
# vLLM-style arg compat: chart deployment passes `--model X --port N`.
# We just exec uvicorn — the unknown flags are dropped by `shift` loop.
# Port stays hard-coded to 8000 to match the chart's Service.
set -eu
while [ "$#" -gt 0 ]; do
    case "$1" in
        --model) shift 2 ;;
        --port)  PORT="$2"; shift 2 ;;
        *)       shift ;;
    esac
done
exec uvicorn server:app --host 0.0.0.0 --port "${PORT:-8000}"