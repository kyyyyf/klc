/**
 * statusBar.ts — status bar item showing active ticket + phase.
 */

import * as vscode from "vscode";
import { TicketMeta, parseState } from "./klcReader";

export class KlcStatusBar {
  private item: vscode.StatusBarItem;
  private workspaceRoot: string;

  constructor(workspaceRoot: string) {
    this.workspaceRoot = workspaceRoot;
    this.item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    this.item.command = "klc.switchTicket";
    this.hide();
  }

  update(tickets: TicketMeta[], activeKey?: string): void {
    if (tickets.length === 0) {
      this.hide();
      return;
    }

    const active = activeKey
      ? tickets.find(t => t.ticket === activeKey)
      : tickets[0];

    if (!active) {
      this.hide();
      return;
    }

    const { phaseId, state } = parseState(active.phase);
    const blocked = active.blocked_reason ? " ⛔" : "";
    const stateHint = state === "ack-needed" ? "→ ack" : state === "ack" ? "→ next" : "working";

    if (tickets.length === 1) {
      this.item.text = `$(klc)$(circle-filled) ${active.ticket} · ${phaseId} · ${stateHint}${blocked}`;
    } else {
      this.item.text = `$(circle-filled) ${active.ticket} · ${phaseId} · ${stateHint}${blocked}  (+${tickets.length - 1})`;
    }

    this.item.tooltip = `klc: ${active.ticket} — ${active.phase}${active.blocked_reason ? `\n⛔ ${active.blocked_reason}` : ""}\nClick to switch ticket`;
    this.item.backgroundColor = active.blocked_reason
      ? new vscode.ThemeColor("statusBarItem.errorBackground")
      : undefined;
    this.item.show();
  }

  hide(): void {
    this.item.hide();
  }

  dispose(): void {
    this.item.dispose();
  }
}
