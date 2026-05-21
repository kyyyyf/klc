/**
 * extension.ts — entry point.
 *
 * Wires together: KlcTreeProvider, KlcStatusBar, KlcWatcher,
 * and command handlers.
 */

import * as vscode from "vscode";
import * as fs from "fs";
import { KlcTreeProvider } from "./treeProvider";
import { KlcStatusBar } from "./statusBar";
import { KlcWatcher } from "./watcher";
import { liveTickets, resolveFrameworkRoot } from "./klcReader";

let activeTicketKey: string | undefined;

export function activate(context: vscode.ExtensionContext): void {
  const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (!workspaceRoot) return;

  const shimPath: string = vscode.workspace
    .getConfiguration("klc")
    .get("shimPath", ".klc/bin/klc");

  const frameworkRoot = resolveFrameworkRoot(workspaceRoot, shimPath);

  const treeProvider = new KlcTreeProvider(workspaceRoot, frameworkRoot);
  const statusBar = new KlcStatusBar(workspaceRoot);
  const watcher = new KlcWatcher(workspaceRoot, () => refresh());

  vscode.window.registerTreeDataProvider("klcNextSteps", treeProvider);
  watcher.start();

  function refresh(): void {
    const tickets = liveTickets(workspaceRoot as string);
    if (!activeTicketKey && tickets.length > 0) {
      activeTicketKey = tickets[0].ticket;
    }
    statusBar.update(tickets, activeTicketKey);
    treeProvider.refresh();
  }

  // Initial render
  refresh();

  // ---- Commands ----

  context.subscriptions.push(
    vscode.commands.registerCommand("klc.refresh", () => refresh()),

    vscode.commands.registerCommand("klc.copyPrompt", async (args: { promptCard?: string }) => {
      const card = args?.promptCard;
      if (!card || !fs.existsSync(card)) {
        vscode.window.showWarningMessage("klc: prompt card not found. Run `klc next` first.");
        return;
      }
      const text = fs.readFileSync(card, "utf8");
      await vscode.env.clipboard.writeText(text);
      vscode.window.showInformationMessage("klc: prompt copied — paste into your agent.");
    }),

    vscode.commands.registerCommand("klc.openPromptCard", async (args: { promptCard?: string }) => {
      const card = args?.promptCard;
      if (!card || !fs.existsSync(card)) {
        vscode.window.showWarningMessage("klc: prompt card not found. Run `klc next` first.");
        return;
      }
      const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(card));
      await vscode.window.showTextDocument(doc);
    }),

    vscode.commands.registerCommand("klc.runInTerminal", (args: { cmd?: string }) => {
      const cmd = args?.cmd;
      if (!cmd) return;
      const terminal = getOrCreateTerminal();
      terminal.show(true);
      terminal.sendText(cmd, false); // paste without Enter — person decides when to run
    }),

    vscode.commands.registerCommand("klc.copyCommand", async (args: { cmd?: string }) => {
      const cmd = args?.cmd;
      if (!cmd) return;
      await vscode.env.clipboard.writeText(cmd);
      vscode.window.showInformationMessage(`klc: copied → ${cmd}`);
    }),

    vscode.commands.registerCommand("klc.ship", (args: { cmd?: string }) => {
      const cmd = args?.cmd;
      if (!cmd) return;
      const terminal = getOrCreateTerminal();
      terminal.show(true);
      terminal.sendText(cmd, false);
    }),

    vscode.commands.registerCommand("klc.switchTicket", async () => {
      const tickets = liveTickets(workspaceRoot);
      if (tickets.length === 0) {
        vscode.window.showInformationMessage("klc: no live tickets.");
        return;
      }
      const items = tickets.map(t => ({
        label: t.ticket,
        description: t.phase,
        detail: t.blocked_reason ? `⛔ ${t.blocked_reason}` : undefined,
      }));
      const picked = await vscode.window.showQuickPick(items, { placeHolder: "Select active ticket" });
      if (picked) {
        activeTicketKey = picked.label;
        refresh();
      }
    }),
  );

  context.subscriptions.push(statusBar, watcher);
}

export function deactivate(): void {}

// -------------------------------------------------------------------------- //

function getOrCreateTerminal(): vscode.Terminal {
  const existing = vscode.window.terminals.find(t => t.name === "klc");
  return existing ?? vscode.window.createTerminal("klc");
}
