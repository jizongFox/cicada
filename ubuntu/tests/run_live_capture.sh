#!/usr/bin/env bash
# Run under dbus-run-session with the requested audio server installed.
set -euo pipefail
export XDG_RUNTIME_DIR
XDG_RUNTIME_DIR=$(mktemp -d)
export PULSE_SERVER="unix:$XDG_RUNTIME_DIR/pulse/native"
pids=()

cleanup() {
    status=$?
    if (("${#pids[@]}")); then
        kill "${pids[@]}" 2>/dev/null || true
        wait "${pids[@]}" 2>/dev/null || true
    fi
    if ((status)); then
        cat "$XDG_RUNTIME_DIR/"*.log
    fi
    rm -rf "$XDG_RUNTIME_DIR"
}
trap cleanup EXIT

wait_socket() {
    for _ in {1..100}; do
        [[ -S "$1" ]] && return
        sleep .05
    done
    echo "Missing server socket: $1" >&2
    return 1
}

case "${1:-}" in
    pulseaudio)
        pulseaudio -n --daemonize=no --use-pid-file=no --exit-idle-time=-1 \
            --load=module-native-protocol-unix > "$XDG_RUNTIME_DIR/pulse.log" 2>&1 &
        pids+=("$!")
        ;;
    pipewire)
        pipewire > "$XDG_RUNTIME_DIR/pipewire.log" 2>&1 &
        pids+=("$!")
        wait_socket "$XDG_RUNTIME_DIR/pipewire-0"
        wireplumber > "$XDG_RUNTIME_DIR/wireplumber.log" 2>&1 &
        pids+=("$!")
        pipewire-pulse > "$XDG_RUNTIME_DIR/pulse.log" 2>&1 &
        pids+=("$!")
        ;;
    *)
        echo 'Expected pulseaudio or pipewire.' >&2
        exit 2
        ;;
esac
wait_socket "$XDG_RUNTIME_DIR/pulse/native"
pactl info
PYTHONPATH=ubuntu python3 ubuntu/tests/live_capture.py
