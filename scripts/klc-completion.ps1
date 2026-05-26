# Bash-like completion for klc inside PowerShell.
#
# Source from your $PROFILE:
#   . \path\to\klc\scripts\klc-completion.ps1
#
# Completes subcommands and ticket keys (live tickets in .klc/tickets/).

$script:KlcSubcmds = @(
    'intake', 'status', 'next', 'ack', 'ship', 'jump', 'abort', 'step',
    'board', 'doctor', 'metrics', 'reindex', 'install',
    'init', 'update'
)

Register-ArgumentCompleter -Native -CommandName klc, klc.ps1, klc.cmd -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    $tokens = @($commandAst.CommandElements)
    if ($tokens.Count -le 2) {
        return $script:KlcSubcmds |
            Where-Object { $_ -like "$wordToComplete*" } |
            ForEach-Object {
                [System.Management.Automation.CompletionResult]::new(
                    $_, $_, 'ParameterValue', $_
                )
            }
    }

    $root = if ($env:PROJECT_ROOT) { $env:PROJECT_ROOT } else { (Get-Location).Path }
    $tickets = Join-Path $root '.klc\tickets'
    if (-not (Test-Path $tickets)) { return @() }

    Get-ChildItem -Directory -Path $tickets |
        Where-Object { $_.Name -ne 'archive' -and $_.Name -like "$wordToComplete*" } |
        ForEach-Object {
            [System.Management.Automation.CompletionResult]::new(
                $_.Name, $_.Name, 'ParameterValue', $_.Name
            )
        }
}
