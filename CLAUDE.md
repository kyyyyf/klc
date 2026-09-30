# KLC project — Claude Code instructions

## Starting a ticket

Before any implementation work:

1. Switch to main, pull all remotes, and bring main up to date with the most
   recent upstream commits across all configured remotes.
2. Create a feature branch: `git checkout -b feature/<branch-name>`.
   Never work on main directly.

## Mandatory: external code review subagent before review-report

When implementing a KLC ticket and writing the review-report, **always** launch
a fresh (non-fork) code-reviewer subagent before writing `review-report.md`.

**Why**: internal review suffers from confirmation bias — the implementer knows
the intent and validates against ACs as written, not against the full codebase.
A fresh subagent catches cross-file gaps (e.g. a file was omitted from scope)
and intra-file contradictions introduced during build. KLC-035 through KLC-037
all had Codex findings that internal review missed for exactly this reason.

**How**:

```
Agent({
  subagent_type: "code-reviewer",   # fresh, no conversation context
  prompt: """
    Review the changes on branch <branch-name> for ticket <KEY>.
    Spec ACs: <paste from spec.md>
    Changed files: <git diff --name-only main..HEAD>

    Read each changed file in full. Check:
    1. Every AC is satisfied in code/prompts/tests.
    2. No related file was missed (e.g. if design.md got a rule, do other
       agent prompts for the same task also need it?).
    3. No intra-file contradictions introduced by the new additions.
    4. Tests cover the new behaviour (not just happy-path).

    Return: ONE JSON object {"findings": [{id, rule_name, severity, file, line, title, body, fix, ac}]}; empty findings if none.
    Take it in with: python3 core/skills/handback.py take --kind code-review --ticket KEY --file answer.json
  """
})
```

Wait for the result before writing `review-report.md`. Assess each finding
(fix / won't fix + reason) and document the assessment in the report.

**Do not skip this step even for small or "obvious" changes.**

## Pushing

After implementation, push the feature branch to all configured remotes.
Before pushing, rebase onto the latest upstream main to avoid conflicts.

## Other reminders

- Always use `PROJECT_ROOT=/home/ek/projects/klc`.
- Scope expansion at `ack`: update `meta.json:affected_modules` rather than fighting it.

## Regenerating the plugin (mandatory after a source edit)

The deployed plugin under `klc-plugin/` (agents, passthrough skills, command
stubs, and `.claude-plugin/plugin.json`) is GENERATED from source — it is never
hand-edited. After editing any `core/agents/*.md` prompt or the `VERB_SPECS`
verb-dictionary in `core/skills/plugin_gen.py`, run `python3 core/skills/plugin_gen.py`
and commit the regenerated `klc-plugin/` files.

The rule is enforced mechanically, not just documented: the drift-guard
`tests/test_plugin_agents_in_sync.py` turns any stale plugin artifact into a red
test (agents + skills byte-exact, manifest byte-exact, bespoke-skill presence,
skill-dir set-closure, and the shared command-description assertion), and the
`hooks/pre-commit` step runs `plugin_gen.py --check-if-staged` whenever a plugin
source is staged and fails the commit on drift. The bespoke skills `run` and
`discuss-feature` stay handwritten (presence-guarded only).

One manual caveat: changing a shared verb's `short` in `VERB_SPECS` regenerates
that verb's `SKILL.md` but NOT its command stub (command stubs are
skip-if-exists), so you must also hand-edit `klc-plugin/commands/<verb>.md` to
match — the drift-guard and the pre-commit gate will flag `CMD-DESC-DRIFT` until
you do.


## Язык и ясность

1. **Писать полными, законченными предложениями.** Не использовать телеграфный стиль с обрывками и тире вместо глаголов. Плохо: «главное — в надёжности и скорости». Хорошо: «Главное — обеспечить надёжность работы и высокую скорость».

2. **Не вставлять английские нарицательные слова в русскую грамматику.** Слова вроде *scope, deadline, issue, feature, release, backlog, gate, handover, health* переводить на устоявшийся русский:
   - scope → «объём работ»
   - deadline → «срок»
   - issue → «задача» или «дефект» (по смыслу)
   - feature → «фича» (слово уже устоялось) или «функция»
   - release → «релиз» (устоялось) или «выпуск»
   - backlog → «бэклог» (устоялось) или «очередь задач»
   - gate → «контрольная точка», «этап приёмки»
   - handover → «передача»
   - health → «состояние»

3. **Если английский термин технический и общепринятый, а русского эквивалента нет** — дать его на английском и пояснить по-русски при первом употреблении. Пример: «rate limiting (ограничение частоты запросов)».

4. **Названия инструментов, продуктов и типов сущностей оставлять как есть**, но обязательно пояснять их роль по-русски при первом упоминании. Пример: «Grafana — панель для просмотра метрик в реальном времени».

5. **Не нагромождать несколько терминов в одной фразе.** Одна мысль — одно предложение.

6. **Не писать роботским, канцелярским языком.** Писать живо и по-человечески, как пишет специалист коллеге, а не как отчёт машины. (Принцип из образцового примера — «Don't embarrass me with robot speak»: «не позорь меня роботским языком».)

## Документы и структура

Эти принципы взяты из хорошего образца оформления и применимы к любым документам и заметкам о коде.

1. **Связка «объект → назначение».** Для каждого важного файла, модуля или сущности коротко указывать, за что он отвечает. Это упрощает навигацию.

2. **Контекст важнее описания.** Объяснять не только *что* сделано, но и *почему* выбран именно такой вариант. Причина решения ценнее, чем его пересказ.

3. **Явно описывать необычные решения.** Всё нестандартное отдельно пояснять, чтобы не путать читателя и не провоцировать «исправление» того, что сделано намеренно.

## Ориентир

Связный текст, простые схемы процессов в блоках ```text```, короткие списки. Ясность важнее полноты.