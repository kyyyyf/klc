# Bash completion for the `klc` dispatcher.
#
# Source from your bashrc:
#   source /path/to/framework/scripts/klc-completion.bash
#
# Completes subcommands, operational verbs, and live-ticket keys
# from `.klc/tickets/`.

_klc() {
    local cur prev words cword
    _init_completion || return

    local subcmds="intake status next ack jump abort board doctor metrics reindex install init update"

    if [ "$cword" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "$subcmds" -- "$cur") )
        return
    fi

    # Ticket keys — read from .klc/tickets/
    local project_root="${PROJECT_ROOT:-$PWD}"
    local tickets_dir="$project_root/.klc/tickets"
    if [ -d "$tickets_dir" ]; then
        local keys=""
        for d in "$tickets_dir"/*/; do
            [ -d "$d" ] || continue
            local base="$(basename "$d")"
            [ "$base" != "archive" ] && keys="$keys $base"
        done
        COMPREPLY=( $(compgen -W "$keys" -- "$cur") )
    fi
}

complete -F _klc klc
