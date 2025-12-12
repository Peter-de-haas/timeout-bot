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

VENV_DIR="$HOME_DIR/timeout-bot/venv"
BOT_SCRIPT="$HOME_DIR/timeout-bot/bot.py"

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

setup_venv() {
    if [[ ! -d "$VENV_DIR" ]]; then
        log "INFO" "Creating Python virtual environment at $VENV_DIR"
        python3 -m venv "$VENV_DIR"
    fi

    log "INFO" "Activating virtual environment"
    # shellcheck disable=SC1090
    source "$VENV_DIR/bin/activate"

    log "INFO" "Installing/updating dependencies"
    pip install --upgrade pip
    pip install --upgrade discord.py
}

########################################
# VALIDATION
########################################

[[ ! -d "$LOG_DIR" ]] && fatal "Missing log directory: $LOG_DIR"
[[ ! -d "$CRED_DIR" ]] && fatal "Missing credentials directory: $CRED_DIR"
[[ ! -f "$CRED_FILE" ]] && fatal "Credentials file missing: $CRED_FILE"
[[ ! -f "$BOT_SCRIPT" ]] && fatal "Bot script missing: $BOT_SCRIPT"

########################################
# LOAD CREDENTIALS
########################################

# shellcheck disable=SC1090
source "$CRED_FILE" || fatal "Could not load credentials"

[[ -z "${DISCORD_TOKEN:-}" ]] && fatal "DISCORD_TOKEN missing in $CRED_FILE"
[[ -z "${CHANNEL_ID:-}" ]] && fatal "CHANNEL_ID missing in $CRED_FILE"
[[ -z "${COOLDOWN_ROLE_ID:-}" ]] && fatal "COOLDOWN_ROLE_ID missing in $CRED_FILE"

########################################
# CLEANUP OLD LOGS
########################################

cleanup_logs

########################################
# SETUP VENV AND DEPENDENCIES
########################################

setup_venv

########################################
# RUN THE BOT
########################################

log "INFO" "Launching timeout bot…"

python "$BOT_SCRIPT" \
    --token "$DISCORD_TOKEN" \
    --cooldown-channel "$CHANNEL_ID" \
    --cooldown-role "$COOLDOWN_ROLE_ID" \
    >> "$LOG_FILE" 2>&1 || fatal "Bot crashed!"

log "INFO" "Bot exited normally"
