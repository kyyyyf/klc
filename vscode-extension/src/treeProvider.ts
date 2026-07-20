/**
 * treeProvider.ts — VS Code TreeDataProvider for "klc · Next Steps".
 */

import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import { TicketState, buildTicketState, liveTickets, parseState } from "./klcReader";

// -------------------------------------------------------------------------- //
// Tree item kinds

type ItemKind =
  | "ticket"
  | "llm-step"
  | "shell-step"
  | "blocker"
  | "info"
  | "action";

export class KlcTreeItem extends vscode.TreeItem {
  constructor(
    public readonly kind: ItemKind,
    label: string,
    collapsible: vscode.TreeItemCollapsibleState,
    public readonly ticketKey?: string,
    public readonly payload?: Record<string, unknown>
  ) {
    super(label, collapsible);
  }
}

// -------------------------------------------------------------------------- //

export class KlcTreeProvider implements vscode.TreeDataProvider<KlcTreeItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<KlcTreeItem | undefined | null>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private workspaceRoot: string;
  private frameworkRoot: string | null;

  constructor(workspaceRoot: string, frameworkRoot: string | null) {
    this.workspaceRoot = workspaceRoot;
    this.frameworkRoot = frameworkRoot;
  }

  refresh(): void {
    this._onDidChangeTreeData.fire(undefined);
  }

  setFrameworkRoot(root: string | null): void {
    this.frameworkRoot = root;
    this.refresh();
  }

  getTreeItem(element: KlcTreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: KlcTreeItem): KlcTreeItem[] {
    if (!element) {
      return this.ticketNodes();
    }
    if (element.kind === "ticket" && element.ticketKey) {
      return this.ticketChildren(element.ticketKey);
    }
    if (element.kind === "llm-step" && element.ticketKey) {
      return this.llmStepChildren(element.ticketKey, element.payload);
    }
    if (element.kind === "shell-step" && element.ticketKey) {
      return this.shellStepChildren(element.ticketKey, element.payload);
    }
    return [];
  }

  // ------------------------------------------------------------------------ //

  private ticketNodes(): KlcTreeItem[] {
    const tickets = liveTickets(this.workspaceRoot);
    if (tickets.length === 0) {
      const empty = new KlcTreeItem("info", "No live tickets — run klc intake", vscode.TreeItemCollapsibleState.None);
      empty.iconPath = new vscode.ThemeIcon("info");
      return [empty];
    }
    return tickets.map(t => {
      const { phaseId, state } = parseState(t.phase);
      const stateIcon = t.blocked_reason ? "error" : state === "ack-needed" ? "pass-filled" : state === "ack" ? "check" : "circle-filled";
      const node = new KlcTreeItem(
        "ticket",
        t.ticket,
        vscode.TreeItemCollapsibleState.Expanded,
        t.ticket
      );
      node.description = `${phaseId} · ${state}`;
      node.tooltip = t.jira_url ?? t.phase;
      node.iconPath = new vscode.ThemeIcon(stateIcon);
      node.contextValue = "klcTicket";
      return node;
    });
  }

  private ticketChildren(ticketKey: string): KlcTreeItem[] {
    if (!this.frameworkRoot) {
      const warn = new KlcTreeItem("info", "klc framework not found — check klc.shimPath setting", vscode.TreeItemCollapsibleState.None);
      warn.iconPath = new vscode.ThemeIcon("warning");
      return [warn];
    }
    const ts = buildTicketState(this.workspaceRoot, this.frameworkRoot, ticketKey);
    if (!ts) {
      return [makeInfo("Cannot read meta.json")];
    }
    const items: KlcTreeItem[] = [];

    // Blockers first
    for (const b of ts.blockers) {
      const bi = new KlcTreeItem("blocker", `⛔ ${b}`, vscode.TreeItemCollapsibleState.None, ticketKey);
      bi.iconPath = new vscode.ThemeIcon("error");
      items.push(bi);
    }

    if (ts.state === "archived") {
      items.push(makeInfo("Archived"));
      return items;
    }

    if (ts.state === "work") {
      items.push(this.llmStepNode(ts));
    } else if (ts.state === "ack-needed") {
      items.push(this.shellStepNode(ts));
    } else {
      // ack — run next
      items.push(this.nextStepNode(ts));
    }

    return items;
  }

  private llmStepNode(ts: TicketState): KlcTreeItem {
    const hasPrompt = ts.promptCard !== null;
    const desc = ts.phase?.prompt
      ? path.basename(ts.phase.prompt)
      : "(no agent — manual step)";
    const node = new KlcTreeItem(
      "llm-step",
      `LLM: ${ts.phaseId}`,
      vscode.TreeItemCollapsibleState.Expanded,
      ts.meta.ticket,
      { promptCard: ts.promptCard, phaseId: ts.phaseId }
    );
    node.description = desc;
    node.iconPath = new vscode.ThemeIcon(hasPrompt ? "sparkle" : "edit");
    return node;
  }

  private llmStepChildren(ticketKey: string, payload?: Record<string, unknown>): KlcTreeItem[] {
    const items: KlcTreeItem[] = [];
    const promptCard = payload?.promptCard as string | undefined;

    if (promptCard) {
      const copy = makeAction(ticketKey, "$(copy) Copy prompt", "klc.copyPrompt", { promptCard });
      items.push(copy);
      const open = makeAction(ticketKey, "$(go-to-file) Open prompt card", "klc.openPromptCard", { promptCard });
      items.push(open);
    } else {
      items.push(makeInfo("Prompt card not yet generated — run klc next"));
    }
    return items;
  }

  private shellStepNode(ts: TicketState): KlcTreeItem {
    const ackCmd = buildAckCommand(this.workspaceRoot, ts);
    const node = new KlcTreeItem(
      "shell-step",
      "Shell: ack-needed",
      vscode.TreeItemCollapsibleState.Expanded,
      ts.meta.ticket,
      { ackCmd, singlePick: ts.singlePick, phase: ts.phase, phaseId: ts.phaseId }
    );
    node.description = ackCmd;
    node.iconPath = new vscode.ThemeIcon("terminal");
    return node;
  }

  private shellStepChildren(ticketKey: string, payload?: Record<string, unknown>): KlcTreeItem[] {
    const items: KlcTreeItem[] = [];
    const ackCmd = payload?.ackCmd as string | undefined;
    const singlePick = payload?.singlePick as { id: number; label: string } | undefined;

    if (ackCmd) {
      items.push(makeAction(ticketKey, "$(run) Run in terminal", "klc.runInTerminal", { cmd: ackCmd }));
      items.push(makeAction(ticketKey, "$(copy) Copy command", "klc.copyCommand", { cmd: ackCmd }));
      if (singlePick) {
        const shipCmd = ackCmd.replace(/^klc ack/, "klc ship");
        items.push(makeAction(ticketKey, `$(zap) Ship (${singlePick.label})`, "klc.ship", { cmd: shipCmd }));
      }
    }

    // Show all picks so user knows what options exist
    const phase = payload?.phase as { picks: Array<{ id: number; label: string }> } | undefined;
    if (phase?.picks?.length) {
      for (const pk of phase.picks) {
        const info = makeInfo(`  ${pk.id} = ${pk.label}`);
        info.iconPath = new vscode.ThemeIcon("symbol-enum-member");
        items.push(info);
      }
    }

    return items;
  }

  private nextStepNode(ts: TicketState): KlcTreeItem {
    const cmd = shimCmd(this.workspaceRoot, `next ${ts.meta.ticket}`);
    const node = new KlcTreeItem(
      "shell-step",
      "Shell: advance to next phase",
      vscode.TreeItemCollapsibleState.Expanded,
      ts.meta.ticket,
      { ackCmd: cmd, singlePick: null, phase: ts.phase, phaseId: ts.phaseId }
    );
    node.description = cmd;
    node.iconPath = new vscode.ThemeIcon("arrow-right");
    return node;
  }
}

// -------------------------------------------------------------------------- //
// helpers

function makeInfo(label: string): KlcTreeItem {
  const item = new KlcTreeItem("info", label, vscode.TreeItemCollapsibleState.None);
  item.iconPath = new vscode.ThemeIcon("info");
  return item;
}

function makeAction(
  ticketKey: string,
  label: string,
  command: string,
  args: Record<string, unknown>
): KlcTreeItem {
  const item = new KlcTreeItem("action", label, vscode.TreeItemCollapsibleState.None, ticketKey, args);
  item.command = { command, title: label, arguments: [args] };
  return item;
}

function shimCmd(workspaceRoot: string, args: string): string {
  const shimPath: string = vscode.workspace
    .getConfiguration("klc")
    .get("shimPath", ".klc/bin/klc");
  const isWindows = process.platform === "win32";
  const shim = shimPath.endsWith(".ps1") || isWindows ? shimPath : shimPath;
  return `${shim} ${args}`;
}

function buildAckCommand(workspaceRoot: string, ts: TicketState): string {
  const base = shimCmd(workspaceRoot, `ack ${ts.meta.ticket}`);
  if (!ts.phase?.pickRequired) return base;
  // A single required pick (e.g. build's 1=approve) must be named explicitly —
  // a bare `klc ack` would be rejected as "pick required" (KLC-072).
  if (ts.phase.picks.length === 1) return `${base} --pick ${ts.phase.picks[0].id}`;
  return `${base} --pick <N>`;
}
