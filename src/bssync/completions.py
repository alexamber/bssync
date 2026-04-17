"""Shell completion scripts.

Printed to stdout by the `completions` subcommand. Users redirect the
output to a completion file or `eval`/`source` it from their shell rc.
"""

import sys


BASH = r"""# bssync bash completion
_bssync_completions() {
    local cur prev
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    local cmd=""
    for w in "${COMP_WORDS[@]:1}"; do
        case "$w" in
            init|push|pull|ls|verify|completions) cmd="$w"; break ;;
        esac
    done

    case "$prev" in
        -c|--config) COMPREPLY=( $(compgen -f -- "$cur") ); return ;;
        --only|--book|--chapter) return ;;
    esac

    if [[ -z "$cmd" ]]; then
        COMPREPLY=( $(compgen -W "init push pull ls verify completions \
            -c --config --verbose -V --version -h --help" -- "$cur") )
        return
    fi

    case "$cmd" in
        push) COMPREPLY=( $(compgen -W "--dry-run --diff --only --force -h --help" -- "$cur") ) ;;
        pull) COMPREPLY=( $(compgen -W "--only --new --book --chapter -h --help" -- "$cur") ) ;;
        ls)   COMPREPLY=( $(compgen -W "--book --chapter --missing -h --help" -- "$cur") ) ;;
        completions) COMPREPLY=( $(compgen -W "bash zsh fish" -- "$cur") ) ;;
    esac
}
complete -F _bssync_completions bssync
"""


ZSH = r"""#compdef bssync
# bssync zsh completion

_bssync() {
    local -a commands
    commands=(
        'init:Interactive config setup'
        'push:Upload local → BookStack'
        'pull:Download BookStack → local'
        'ls:List pages on BookStack'
        'verify:Test API connection'
        'completions:Print shell completion script'
    )

    local state

    _arguments -C \
        '(-c --config)'{-c,--config}'[Config file path]:file:_files -g "*.yaml"' \
        '--verbose[Show API request details]' \
        '(-V --version)'{-V,--version}'[Show version]' \
        '(-h --help)'{-h,--help}'[Show help]' \
        '1: :->cmds' \
        '*::arg:->args'

    case $state in
        cmds)
            _describe 'command' commands
            ;;
        args)
            case $words[1] in
                push)
                    _arguments \
                        '--dry-run[Preview without writes]' \
                        '--diff[Show content diff]' \
                        '--only[Filter entries]:filter:' \
                        '--force[Skip conflict check]'
                    ;;
                pull)
                    _arguments \
                        '--only[Filter entries]:filter:' \
                        '--new[Discovery mode]' \
                        '--book[Scope by book]:book name:' \
                        '--chapter[Scope by chapter]:chapter name:'
                    ;;
                ls)
                    _arguments \
                        '--book[Filter by book]:book name:' \
                        '--chapter[Filter by chapter]:chapter name:' \
                        '--missing[Only untracked pages]'
                    ;;
                completions)
                    _values 'shell' bash zsh fish
                    ;;
            esac
            ;;
    esac
}

_bssync "$@"
"""


FISH = r"""# bssync fish completion

# Subcommands
complete -c bssync -n '__fish_use_subcommand' -a 'init' -d 'Interactive config setup'
complete -c bssync -n '__fish_use_subcommand' -a 'push' -d 'Upload local → BookStack'
complete -c bssync -n '__fish_use_subcommand' -a 'pull' -d 'Download BookStack → local'
complete -c bssync -n '__fish_use_subcommand' -a 'ls' -d 'List pages on BookStack'
complete -c bssync -n '__fish_use_subcommand' -a 'verify' -d 'Test API connection'
complete -c bssync -n '__fish_use_subcommand' -a 'completions' -d 'Print shell completion script'

# Global flags
complete -c bssync -s c -l config -r -d 'Config file path'
complete -c bssync -l verbose -d 'Show API request details'
complete -c bssync -s V -l version -d 'Show version'
complete -c bssync -s h -l help -d 'Show help'

# push flags
complete -c bssync -n '__fish_seen_subcommand_from push' -l dry-run -d 'Preview without writes'
complete -c bssync -n '__fish_seen_subcommand_from push' -l diff -d 'Show content diff'
complete -c bssync -n '__fish_seen_subcommand_from push' -l only -r -d 'Filter entries'
complete -c bssync -n '__fish_seen_subcommand_from push' -l force -d 'Skip conflict check'

# pull flags
complete -c bssync -n '__fish_seen_subcommand_from pull' -l only -r -d 'Filter entries'
complete -c bssync -n '__fish_seen_subcommand_from pull' -l new -d 'Discovery mode'
complete -c bssync -n '__fish_seen_subcommand_from pull' -l book -r -d 'Scope by book'
complete -c bssync -n '__fish_seen_subcommand_from pull' -l chapter -r -d 'Scope by chapter'

# ls flags
complete -c bssync -n '__fish_seen_subcommand_from ls' -l book -r -d 'Filter by book'
complete -c bssync -n '__fish_seen_subcommand_from ls' -l chapter -r -d 'Filter by chapter'
complete -c bssync -n '__fish_seen_subcommand_from ls' -l missing -d 'Only untracked pages'

# completions
complete -c bssync -n '__fish_seen_subcommand_from completions' -a 'bash zsh fish'
"""


SCRIPTS = {"bash": BASH, "zsh": ZSH, "fish": FISH}


def cmd_completions(shell: str) -> None:
    script = SCRIPTS.get(shell)
    if script is None:
        print(f"Unknown shell: {shell}. Choose from: bash, zsh, fish",
              file=sys.stderr)
        sys.exit(1)
    sys.stdout.write(script)
