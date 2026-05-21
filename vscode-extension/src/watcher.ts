// watcher.ts — file system watcher for .klc/tickets/<key>/meta.json.
// Debounces changes and fires a callback. No state mutation — the
// callback re-reads everything from disk.

import * as vscode from "vscode";
import * as path from "path";

export class KlcWatcher {
  private watcher: vscode.FileSystemWatcher | null = null;
  private debounceTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly debounceMs = 300;

  constructor(
    private workspaceRoot: string,
    private onChanged: () => void
  ) {}

  start(): void {
    const pattern = new vscode.RelativePattern(
      this.workspaceRoot,
      ".klc/tickets/*/meta.json"
    );
    this.watcher = vscode.workspace.createFileSystemWatcher(pattern);

    const handler = () => {
      if (this.debounceTimer) clearTimeout(this.debounceTimer);
      this.debounceTimer = setTimeout(() => this.onChanged(), this.debounceMs);
    };

    this.watcher.onDidChange(handler);
    this.watcher.onDidCreate(handler);
    this.watcher.onDidDelete(handler);

    // Also watch prompt cards so tree refreshes when klc writes _prompt.md
    const promptPattern = new vscode.RelativePattern(
      this.workspaceRoot,
      ".klc/tickets/*/*/_prompt*.md"
    );
    const promptWatcher = vscode.workspace.createFileSystemWatcher(promptPattern);
    promptWatcher.onDidCreate(handler);
    promptWatcher.onDidChange(handler);
  }

  dispose(): void {
    if (this.debounceTimer) clearTimeout(this.debounceTimer);
    this.watcher?.dispose();
  }
}
