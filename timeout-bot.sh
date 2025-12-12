#!/usr/bin/env bash
set -Eeuo pipefail

########################################
# CONFIGURATION
########################################

HOME_DIR="$HOME"
SCRIPT_NAME="timeout-bot"

LOG_DIR="$HOME_DIR/logs"
CRED_DIR="$HOME_DIR/credentials"
CRED_FILE="$CRED_DIR/${SCRIPT_NAME}.conf"

TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"
TODAY="$(date '+%Y-%m-%d')"
LOG_FILE="$LOG_DIR/${SCRIPT_NAME}-${TODAY}.log"

RETENTION_DAYS=7

########################################
# FUNCTIONS
########################################

log() {
    local level="$1"
    local message="$2"
    echo "[$TIMESTAMP] [$level] $message" | tee -a "$LOG_FILE" >&2
}

fatal() {
    log "ERROR" "$1"
    exit 1
}

cleanup_logs() {
    find "$LOG_DIR" -type f -name "${SCRIPT_NAME}-*.log" -mtime +"$RETENTION_DAYS" -exec rm -f {} \;
}

########################################
# VALIDATION
########################################

[[ ! -d "$LOG_DIR" ]] && fatal "Missing log directory: $LOG_DIR"
[[ ! -d "$CRED_DIR" ]] && fatal "Missing credentials directory: $CRED_DIR"
[[ ! -f "$CRED_FILE" ]] && fatal "Credentials file missing: $CRED_FILE"

########################################
# LOAD CREDENTIALS
########################################

source "$CRED_FILE" || fatal "Could not load credentials"

[[ -z "${DISCORD_TOKEN:-}" ]] && fatal "DISCORD_TOKEN missing in credentials"
[[ -z "${CHANNEL_ID:-}" ]] && fatal "CHANNEL_ID missing in credentials"
[[ -z "${COOLDOWN_ROLE_ID:-}" ]] && fatal "COOLDOWN_ROLE_ID missing in credentials"

########################################
# LOG CLEANUP
########################################

cleanup_logs

########################################
# RUN THE PYTHON BOT
########################################

log "INFO" "Launching timeout bot…"

python3 "$HOME_DIR/timeout-bot/bot.py" \
    --token "$DISCORD_TOKEN" \
    --cooldown-channel "$CHANNEL_ID" \
    --cooldown-role "$COOLDOWN_ROLE_ID" \
    >> "$LOG_FILE" 2>&1 || fatal "Bot crashed!"

log "INFO" "Bot exited normally"
