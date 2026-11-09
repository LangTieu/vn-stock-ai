#!/bin/bash
# Cai LiteLLM Proxy (port 4000) tren may MOI — dung cho VN Stock AI + coding.
# Key (Cerebras/BeatAPI/LLM7/Gemini/Radox) dua SAU: start.sh chi export
# key nao co file (thieu thi bo qua), LiteLLM van len va tra /health;
# model nao thieu key se loi khi goi, fallback sang leg co key.
# Dung: bash setup_litellm.sh <DIR>   (vd /home/agentuser/litellm | /data/home/litellm)
# Yeu cau: config.yaml + strip_reasoning.py da co trong DIR (upload truoc).
set -e
DIR="$1"
[ -n "$DIR" ] || { echo "usage: $0 <DIR>"; exit 1; }
mkdir -p "$DIR"
cd "$DIR"

# 1. venv + litellm
if [ ! -x "$DIR/venv/bin/python" ]; then
  python3 -m venv "$DIR/venv"
  echo "venv created"
fi
"$DIR/venv/bin/pip" install --quiet --upgrade pip
"$DIR/venv/bin/pip" install --quiet 'litellm[proxy]'
"$DIR/venv/bin/litellm" --version
echo "INSTALL-OK"

# 2. master key (moi may 1 key rieng, file 0600)
if [ ! -f "$DIR/.master_key" ]; then
  "$DIR/venv/bin/python" -c "import secrets; print('sk-' + secrets.token_hex(16))" > "$DIR/.master_key"
  chmod 600 "$DIR/.master_key"
  echo "master key created"
fi

# 3. start.sh — export key CHI KHI file ton tai (key dua sau van chay duoc)
cat > "$DIR/start.sh" << 'EOF'
#!/bin/bash
# Start LiteLLM proxy (port 4000). Key doc tu file 0600; file nao chua co
# thi bo qua (key dua sau). Master key bat buoc phai co.
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
export PYTHONPATH="$DIR:$PYTHONPATH"
export LITELLM_MASTER_KEY="$(cat "$DIR/.master_key")"
for k in BEATAPI_API_KEY CEREBRAS_API_KEY LLM7_API_KEY GEMINI_API_KEY RADOX_API_KEY CLOUDFLARE_API_TOKEN; do
  f="$DIR/.$(echo "$k" | tr 'A-Z' 'a-z')"
  [ -f "$f" ] && export "$k"="$(cat "$f")"
done
nohup "$DIR/venv/bin/litellm" --port 4000 --config "$DIR/config.yaml" >> "$DIR/proxy.log" 2>&1 &
echo $! > "$DIR/proxy.pid"
echo "started pid $(cat "$DIR/proxy.pid")"
EOF
chmod +x "$DIR/start.sh"

# 4. keepalive.sh — khoi dong lai neu /health/liveliness khong tra loi
cat > "$DIR/keepalive.sh" << 'EOF'
#!/bin/bash
# Keep-alive cho LiteLLM proxy (chay tu cron 5 phut/lan).
DIR="$(cd "$(dirname "$0")" && pwd)"
if curl -fsS -m 5 http://localhost:4000/health/liveliness >/dev/null 2>&1; then
  exit 0
fi
if [ -f "$DIR/proxy.pid" ]; then
  OLD=$(cat "$DIR/proxy.pid")
  kill "$OLD" 2>/dev/null || true
  sleep 3
  kill -9 "$OLD" 2>/dev/null || true
fi
"$DIR/start.sh" >/dev/null 2>&1
echo "$(date -u +%FT%TZ): proxy down, restarted" >> "$DIR/keepalive.log"
EOF
chmod +x "$DIR/keepalive.sh"

# 5. cron keepalive (5 phut/lan) — them neu chua co; bo qua neu khong co cron
if command -v crontab >/dev/null 2>&1; then
  (crontab -l 2>/dev/null | grep -v "litellm/keepalive.sh"; echo "*/5 * * * * $DIR/keepalive.sh") | crontab -
  echo "cron keepalive set"
else
  echo "no crontab on this machine — keepalive.sh co san, chay tay khi can"
fi

# 6. start + verify health
"$DIR/start.sh"
sleep 10
curl -fsS -m 5 http://localhost:4000/health/liveliness && echo " HEALTH OK"
echo "SETUP-OK dir=$DIR"
