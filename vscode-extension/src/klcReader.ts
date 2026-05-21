/**
 * klcReader.ts — reads klc state directly from .klc/ files.
 *
 * No klc subprocess needed for read operations.
 * Sources:
 *   .klc/tickets/<key>/meta.json         — phase, track, kind, blocked_reason
 *   .klc/tickets/                        — enumerate live tickets
 *   config/phases.yml (framework)        — picks, prompt paths, outputs
 *   .klc/tickets/<key>/<phase>/_prompt.md — rendered prompt card
 */

import * as fs from "fs";
import * as path from "path";

export interface TicketMeta {
  ticket: string;
  phase: string;        // e.g. "build:work"
  track: string;        // XS | S | M | L
  kind: string;
  blocked_reason?: string;
  jira_url?: string;
  modified: number;     // mtime ms, for recency sort
}

export interface PhaseInfo {
  id: string;
  tracks: string[];
  prompt: string;       // relative framework path, empty = no agent
  pickRequired: boolean;
  picks: Pick[];
  inputs: string[];
  outputs: string[];
}

export interface Pick {
  id: number;
  label: string;
  goto: string;
}

export interface TicketState {
  meta: TicketMeta;
  phase: PhaseInfo | null;
  phaseId: string;
  state: "work" | "ack-needed" | "ack" | "archived";
  promptCard: string | null;   // absolute path to _prompt.md if it exists
  blockers: string[];
  singlePick: Pick | null;     // non-null when exactly one unambiguous pick
}

// -------------------------------------------------------------------------- //

export function findTicketsDir(workspaceRoot: string): string {
  return path.join(workspaceRoot, ".klc", "tickets");
}

export function liveTickets(workspaceRoot: string): TicketMeta[] {
  const dir = findTicketsDir(workspaceRoot);
  if (!fs.existsSync(dir)) return [];

  const result: TicketMeta[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name === "archive") continue;
    const metaPath = path.join(dir, entry.name, "meta.json");
    if (!fs.existsSync(metaPath)) continue;
    try {
      const raw = JSON.parse(fs.readFileSync(metaPath, "utf8"));
      const stat = fs.statSync(metaPath);
      result.push({
        ticket: raw.ticket ?? entry.name,
        phase: raw.phase ?? "unknown",
        track: raw.track ?? "?",
        kind: raw.kind ?? "unknown",
        blocked_reason: raw.blocked_reason,
        jira_url: raw.jira_url,
        modified: stat.mtimeMs,
      });
    } catch {
      // unreadable meta — skip
    }
  }
  return result.sort((a, b) => b.modified - a.modified);
}

export function readMeta(workspaceRoot: string, ticketKey: string): TicketMeta | null {
  const metaPath = path.join(findTicketsDir(workspaceRoot), ticketKey, "meta.json");
  if (!fs.existsSync(metaPath)) return null;
  try {
    const raw = JSON.parse(fs.readFileSync(metaPath, "utf8"));
    const stat = fs.statSync(metaPath);
    return {
      ticket: raw.ticket ?? ticketKey,
      phase: raw.phase ?? "unknown",
      track: raw.track ?? "?",
      kind: raw.kind ?? "unknown",
      blocked_reason: raw.blocked_reason,
      jira_url: raw.jira_url,
      modified: stat.mtimeMs,
    };
  } catch {
    return null;
  }
}

// -------------------------------------------------------------------------- //
// phases.yml parser (minimal — no yaml lib needed for our subset)

export function loadPhases(frameworkRoot: string): Map<string, PhaseInfo> {
  const phasesPath = path.join(frameworkRoot, "config", "phases.yml");
  if (!fs.existsSync(phasesPath)) return new Map();
  const text = fs.readFileSync(phasesPath, "utf8");
  return parsePhases(text);
}

function parsePhases(text: string): Map<string, PhaseInfo> {
  const map = new Map<string, PhaseInfo>();
  // Split on "  - id:" phase boundaries
  const blocks = text.split(/^  - id:/m).slice(1);
  for (const block of blocks) {
    const lines = block.split("\n");
    const id = lines[0].trim();
    if (!id) continue;

    const tracksMatch = block.match(/^\s+tracks:\s*\[([^\]]*)\]/m);
    const tracks = tracksMatch
      ? tracksMatch[1].split(",").map(t => t.trim())
      : [];

    const promptMatch = block.match(/^\s+prompt:\s*["']?([^"'\n]*)["']?/m);
    const prompt = promptMatch ? promptMatch[1].trim() : "";

    const pickRequiredMatch = block.match(/^\s+pick_required:\s*(true|false)/m);
    const pickRequired = pickRequiredMatch ? pickRequiredMatch[1] === "true" : false;

    // Parse picks block
    const picks: Pick[] = [];
    const pickSection = block.match(/^\s+picks:([\s\S]*?)(?=^\s+(?:inputs|outputs|auto_ack_after)|$)/m);
    if (pickSection) {
      const pickBlocks = pickSection[1].split(/^\s+- id:/m).slice(1);
      for (const pb of pickBlocks) {
        const pid = parseInt(pb.trim().split(/\s/)[0], 10);
        const labelMatch = pb.match(/label:\s*["']?([^"'\n]+)["']?/);
        const gotoMatch = pb.match(/goto:\s*["']?([^"'\n]+)["']?/);
        if (!isNaN(pid) && labelMatch) {
          picks.push({
            id: pid,
            label: labelMatch[1].trim(),
            goto: gotoMatch ? gotoMatch[1].trim() : "next",
          });
        }
      }
    }

    const inputsMatch = block.match(/^\s+inputs:\s*\[([^\]]*)\]/m);
    const inputs = inputsMatch
      ? inputsMatch[1].split(",").map(s => s.trim().replace(/['"]/g, "")).filter(Boolean)
      : [];

    const outputsMatch = block.match(/^\s+outputs:\s*\[([^\]]*)\]/m);
    const outputs = outputsMatch
      ? outputsMatch[1].split(",").map(s => s.trim().replace(/['"]/g, "")).filter(Boolean)
      : [];

    map.set(id, { id, tracks, prompt, pickRequired, picks, inputs, outputs });
  }
  return map;
}

// -------------------------------------------------------------------------- //

export function parseState(phaseField: string): { phaseId: string; state: "work" | "ack-needed" | "ack" | "archived" } {
  if (phaseField === "archived") return { phaseId: "archived", state: "archived" };
  const parts = phaseField.split(":");
  const stateStr = parts.pop() ?? "work";
  const phaseId = parts.join(":");
  const state = (["work", "ack-needed", "ack"].includes(stateStr) ? stateStr : "work") as "work" | "ack-needed" | "ack";
  return { phaseId, state };
}

export function promptCardPath(
  workspaceRoot: string,
  ticketKey: string,
  phaseId: string,
  step?: number
): string | null {
  const base = path.join(findTicketsDir(workspaceRoot), ticketKey, phaseId);
  const candidates = step !== undefined
    ? [path.join(base, `_prompt_step_${step}.md`), path.join(base, "_prompt.md")]
    : [path.join(base, "_prompt.md")];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return null;
}

export function buildTicketState(
  workspaceRoot: string,
  frameworkRoot: string,
  ticketKey: string
): TicketState | null {
  const meta = readMeta(workspaceRoot, ticketKey);
  if (!meta) return null;

  const phases = loadPhases(frameworkRoot);
  const { phaseId, state } = parseState(meta.phase);
  const phase = phases.get(phaseId) ?? null;

  const promptCard = promptCardPath(workspaceRoot, ticketKey, phaseId);

  const blockers: string[] = [];
  if (meta.blocked_reason) blockers.push(meta.blocked_reason);

  // Single-pick: only when state is ack-needed AND there's exactly one pick
  // OR pick_required is false (no choice needed)
  let singlePick: Pick | null = null;
  if (state === "ack-needed" && phase) {
    if (!phase.pickRequired && phase.picks.length >= 1) {
      singlePick = phase.picks[0];
    } else if (phase.picks.length === 1) {
      singlePick = phase.picks[0];
    }
  }

  return { meta, phase, phaseId, state, promptCard, blockers, singlePick };
}

export function resolveFrameworkRoot(workspaceRoot: string, shimPath: string): string | null {
  // Read the shim file and extract the framework path from it.
  // The shim contains a line like: KLC_FRAMEWORK_ROOT=/opt/klc
  // or: $FW = "C:\klc"
  const fullShim = path.isAbsolute(shimPath)
    ? shimPath
    : path.join(workspaceRoot, shimPath);

  if (!fs.existsSync(fullShim)) return null;

  try {
    const text = fs.readFileSync(fullShim, "utf8");
    // bash shim: KLC_FRAMEWORK_ROOT="..." or similar
    let m = text.match(/KLC_FRAMEWORK_ROOT=["']?([^"'\n]+)["']?/);
    if (m) return m[1].trim();
    // PS1 shim: $FW = "..."
    m = text.match(/\$FW\s*=\s*["']([^"']+)["']/);
    if (m) return m[1].trim();
    // fallback: parent of the shim's scripts/ dir isn't available,
    // but the shim itself might just exec the klc script directly
    // Try extracting any absolute path that looks like a klc root
    m = text.match(/"([^"]+)[/\\]scripts[/\\]klc"/);
    if (m) return m[1].trim();
  } catch {
    // ignore
  }
  return null;
}
