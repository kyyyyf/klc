# Процесс разработки на основе LLM — предложение

> Документ-ответ на вопрос о процессе. Фокус — три механики: разметка
> фактов/предположений/решений, трекинг изменений, "источник правды".
> Фазы процесса описаны кратко; детальная проработка остальных шагов —
> отдельный документ.

## Оглавление

1. [Фазовая модель процесса (recap)](#1-фазовая-модель-процесса-recap)
2. [Inline-разметка фактов/предположений/решений](#2-inline-разметка-фактовпредположенийрешений)
3. [Отслеживание изменений решений и документов](#3-отслеживание-изменений-решений-и-документов)
4. [Источник правды — пять механизмов](#4-источник-правды--пять-механизмов)
5. [Открытые вопросы](#5-открытые-вопросы)

---

## 1. Фазовая модель процесса (recap)

14 шагов исходного описания свёрнуты в 7 фаз. Только три из них требуют
явного human-gate; остальные драйвятся LLM-агентами и доступны человеку
в режиме "опциональный ревью".

| Фаза | Что происходит | Артефакты | Human-gate |
|---|---|---|---|
| 0. Intake | создание тикета | issue (raw description) | — |
| 1. Discovery | обогащение, многомерная оценка, выбор track'а (XS/S/M/L) | `spec.md` | ✅ pull-ready ack |
| 2. Design | options, выбор, ADR (для M/L), impl-plan, test-plan | `design/options.md`, `design/adr.md`, `impl-plan.md`, `test-plan.md` | ✅ direction ack |
| 3. Build | TDD-loop: tests → impl → run → iterate | обновления всех артефактов inline | — (human on signal) |
| 4. Review | один комплексный ревью-pass по всему диффу + артефактам | `review-report.md` | ✅ merge ack |
| 5. Integrate | merge, deploy, observe | merge commit | — |
| 6. Learn | метрики + ретро, обратная связь в knowledge base | `retrospective.md`, обновления allowlist и few-shot examples | — |

Tracks (минимальный набор):

| Track | Примеры | Пропускается |
|---|---|---|
| XS (<0.5 day) | typo, строковый литерал | всё кроме Build + минимального Review |
| S (0.5–2 day) | локальный баг-фикс, мелкий рефакторинг | options, ADR |
| M (2–5 day) | feature в одном модуле | — (ADR опционален) |
| L (>5 day) | кросс-модульная feature, новые зависимости | — (ADR обязателен + deliberate intermediate review) |

Track выбирается LLM на Phase 1 по многомерной оценке
(сложность, неопределённость, риск, ручное тестирование). Human может
поднять track вверх; понижать запрещено (охранный инвариант).

---

## 2. Inline-разметка фактов/предположений/решений

### 2.1. Синтаксис

GFM-admonitions + структурированная первая строка с ID и полями.
Рендерится нативно в GitHub/GitLab/VS Code; парсится простым регэкспом
на заголовке admonition.

```markdown
> [!FACT F-003] src=api/users.py:42 verified=2026-05-08
> UserRepository.save() блокирует I/O на connection pool.

> [!ASSUMPTION A-007] if-false="redesign cache layer" confidence=medium
> Нагрузка на endpoint останется < 100 rps в Q2.

> [!DECISION D-012] owner=ek date=2026-05-08 supersedes=D-005 refs=F-003,A-007
> Оборачиваем save() в async-wrapper вместо переписывания слоя.
> **Reason:** minimal blast radius, 1 day vs 2 weeks.

> [!HYPOTHESIS H-002] verified-by=perf-test-042 status=pending
> p99 latency упадёт ниже 50ms после изменения.

> [!CONSTRAINT C-001] source=legal owner=@legal-team
> Персональные данные не покидают EU-регион.

> [!QUESTION Q-004] blocks=D-012
> Есть ли SLA на response time у этого endpoint?

> [!RISK R-006] probability=low impact=high mitigation=D-012
> Async-wrapper маскирует connection-pool starvation на пике.
```

### 2.2. Типы и поля

| Тип | Обязательные поля | Опциональные поля |
|---|---|---|
| FACT | `src` (file:line, commit, metric) | `verified` |
| ASSUMPTION | `if-false` (что сломается) | `confidence` |
| DECISION | `owner`, `date`, `reason` (в теле) | `supersedes`, `refs` |
| HYPOTHESIS | `verified-by` | `status` |
| CONSTRAINT | `source` | `owner` |
| QUESTION | — | `blocks` |
| RISK | `probability`, `impact` | `mitigation` |

### 2.3. ID и уникальность

- Формат: `<Тип>-NNN` (F-003, A-007, D-012, ...).
- Уникальность — в пределах тикета.
- Монотонный счётчик на тип.
- При супересдации старый ID **не переиспользуется**.
- Cross-ticket ссылки: `TICK-123/D-018`.

### 2.4. Правила для LLM

Явно прописаны в промптах всех агентов:

- Любое утверждение о коде/состоянии → `FACT` с валидным `src`.
- Любое утверждение о будущем без verification → `ASSUMPTION` или `HYPOTHESIS`.
- Любой выбор между альтернативами → `DECISION`.
- Если агент хочет высказаться без указания типа — промпт обязан
  отказаться и попросить уточнения.

### 2.5. Агрегация

Скрипт `tools/collect-items.py` обходит `tickets/TICK-123/**/*.md`,
извлекает admonition-заголовки, строит
`tickets/TICK-123/.index.json` (см. раздел 3.3). Этот JSON — единый
источник для:

- поиска по решениям/фактам
- consistency-check перед merge
- сводного "decisions register" в финальном отчёте тикета
- org-wide knowledge base (см. cross-ticket references)

---

## 3. Отслеживание изменений решений и документов

Три слоя, каждый закрывает свой уровень абстракции.

### 3.1. Слой 1 — Git (контент-diff)

Артефакты тикета живут в ветке задачи:

```
tickets/TICK-123/
  spec.md
  design/
    options.md
    adr.md
  impl-plan.md
  test-plan.md
  retrospective.md
  .index.json       # регенерируется pre-commit
```

Git даёт line-level diff, blame, историю коммитов. Ветка вливается в
main после merge; архив задачи остаётся в git-истории навсегда.

**Важно:** артефакты коммитятся **continuously**, с первого шага Phase
1, а не в конце (шаг 14 исходного описания). Промежуточные состояния —
часть истории.

### 3.2. Слой 2 — Supersession (семантика решений)

`DECISION` **не редактируется в теле**. При пересмотре создаётся новый
item с полем `supersedes=`:

```markdown
> [!DECISION D-012] owner=ek date=2026-05-08 status=superseded
> Оборачиваем save() в async-wrapper.

> [!DECISION D-018] owner=ek date=2026-05-10 supersedes=D-012 refs=H-002
> Переписываем connection pool целиком — async-wrapper не решил starvation.
> **Reason:** H-002 перешла в status=rejected после нагрузочных тестов.
```

Оба остаются в документе. Читатель видит историю решений хронологически,
без необходимости поднимать git blame.

`FACT`, `CONSTRAINT` тоже versionable через supersession (редко).
`ASSUMPTION` и `HYPOTHESIS` обычно переходят в `status=verified`/
`rejected` — это in-place обновление поля, не новый ID. Отличие от
DECISION: решение — активный выбор и должно быть visible в
retrospective; гипотеза — констатация, post-mortem на уровне полей
достаточно.

### 3.3. Слой 3 — Index (cross-artefact)

`tickets/TICK-123/.index.json`, регенерируется pre-commit hook'ом:

```json
{
  "ticket": "TICK-123",
  "items": {
    "D-012": {
      "type": "DECISION",
      "file": "design/adr.md",
      "line": 42,
      "status": "superseded",
      "superseded_by": "D-018",
      "owner": "ek",
      "date": "2026-05-08",
      "refs": ["F-003", "A-007"],
      "referenced_by": ["D-018", "impl-plan.md#step-3"]
    },
    "A-007": {
      "type": "ASSUMPTION",
      "status": "active",
      "if_false": "redesign cache layer",
      "referenced_by": ["D-012", "D-018"]
    }
  },
  "graph": {
    "active_decisions": ["D-018"],
    "superseded": ["D-012"],
    "dangling_refs": [],
    "orphan_assumptions": []
  }
}
```

### 3.4. Pre-merge consistency gate

`tools/consistency-check.py` запускается перед merge и проверяет:

- нет `dangling_refs` (item ссылается на несуществующий ID);
- нет `DECISION` со `status=active`, чья цепочка `refs` упирается в
  rejected ASSUMPTIONs (решение приняли, основание под ним рухнуло);
- нет orphan `QUESTION`s (открытые вопросы, блокирующие решения);
- нет `FACT` с устаревшим `verified` относительно последнего изменения
  кода в `src=` (факт мог стать неверным после правки);
- все `CONFLICT` items разрешены (см. раздел 4.6).

Если gate падает — merge блокируется.

### 3.5. Визуализация

Скрипт `tools/decision-graph.py` рисует DOT/Mermaid-граф:

```
D-005 ──supersedes──> D-012 ──supersedes──> D-018
                        ↑                      ↑
                      A-007 ─────refs──────────┘
```

На Phase 4 ревьювер смотрит на граф, а не на 300-строчный ADR.

### 3.6. Cross-ticket knowledge base

`tickets/.global-index.json` — org-wide граф решений, построенный
слиянием всех `.index.json`. Используется:

- LLM на Phase 1 (Discovery): "этот тикет похож на TICK-089, там
  приняли D-045 — учти";
- ретроспективой: "мы второй раз принимаем такое же решение, стоит
  ли выносить в общий ADR";
- аудитом: "покажи все активные DECISION, ссылающиеся на A-007".

---

## 4. Источник правды — пять механизмов

Проблема: LLM генерирует `impl-plan.md`, человек правит абзац вручную,
LLM regenerate'ит — правка теряется. Или: `spec.md` говорит
"timeout = 30s", ADR говорит "timeout = 60s" — какой авторитет?

Решается пятью механизмами. Каждый закрывает свой класс конфликтов.

### 4.1. Authority per document

YAML frontmatter в каждом артефакте:

```yaml
---
ticket: TICK-123
authority: hybrid
regenerated_by: design-agent
last_generated: 2026-05-08T14:22:00Z
last_human_edit: 2026-05-08T15:10:00Z
---
```

| Authority | Значение | Примеры |
|---|---|---|
| `human` | LLM не перезаписывает никогда; агент только читает | `spec.md` после ack, `retrospective.md` |
| `generated` | регенерируется целиком при каждом запуске агента | сводные reports, `.index.json` |
| `hybrid` | есть manual-блоки внутри generated-тела | `CLAUDE.md`, `impl-plan.md` |

**Правило агента:** если `last_human_edit > last_generated`, перед
regenerate показать diff и попросить подтверждения — regenerate
стирает человеческие правки в non-manual зонах.

### 4.2. Manual blocks внутри hybrid-документов

Принцип от `CLAUDE.md`, расширенный:

```markdown
<!-- BEGIN: manual owner=ek reason="domain knowledge" -->
Эта нода обслуживает legacy-клиентов v1.2, которые не умеют в retry.
Поэтому timeout здесь 60s, а не 30s как в остальном API.
<!-- END: manual -->
```

- `owner` — кто автор блока (для blame без git);
- `reason` — зачем блок существует (чтобы через полгода не снести как
  "непонятное").

**Правило:** LLM при regenerate копирует такие блоки 1-to-1. Если LLM
считает, что блок устарел — **не удаляет**, а добавляет рядом
`[!QUESTION] blocks-generation=yes` и останавливается, ожидая human ack.

### 4.3. Cross-document authority precedence

Иерархия, заданная фиксированно:

| Артефакт | Авторитет на |
|---|---|
| `spec.md` | цели, acceptance criteria, non-goals, constraints |
| `design/adr.md` | решения (DECISION items) |
| `design/options.md` | рассмотренные альтернативы и причины отказа |
| `impl-plan.md` | последовательность шагов реализации |
| `test-plan.md` | что проверяется и как |
| `retrospective.md` | lessons learned, post-mortem |

Если `impl-plan.md` содержит ASSUMPTION, противоречащий FACT в
`spec.md` — **FACT выигрывает**, consistency-check помечает impl-plan
как out-of-date. Агент, регенерирующий impl-plan, обязан сначала
согласоваться со spec.

**Explicit override:** человек может перекрыть precedence, но должен
оставить

```markdown
> [!DECISION D-NNN] overrides=spec.md:AC-3 reason="..."
```

Это делает override видимым и traceable.

### 4.4. Item-level locks

Внутри любого документа отдельный item может быть защищён:

```markdown
> [!DECISION D-012] owner=ek date=2026-05-08 locked=true
> Используем lib X, а не Y, хотя Y технически лучше.
> **Reason:** у команды 5 лет опыта с X, переход — организационный риск.
```

`locked=true` → LLM не трогает, даже если документ имеет
`authority: generated`. Если LLM хочет содержательно изменить locked
item — создаёт новый `D-NNN` с `supersedes=D-012` и оставляет оба, но
статус `D-012` переключить автоматически не может (нужен human ack).

**Расширение:** `locked-until=2026-07-01` — временный lock на период
фичи/релиза.

### 4.5. Regeneration contract (инварианты для LLM)

Явный промпт-контракт, который каждый агент получает:

```text
You are regenerating <artifact>. The following rules are non-negotiable:

1. Preserve any text inside <!-- BEGIN: manual --> ... <!-- END: manual -->
   exactly.
2. Preserve any tagged item with locked=true. If you believe it is wrong,
   emit a QUESTION with blocks-generation=yes and stop.
3. When changing a DECISION, do not edit in place. Create a new DECISION
   with supersedes=<old id>. Both must remain in the file.
4. Before emitting, verify every ref= target exists in the ticket index.
   If a ref points to a superseded item, replace with the active
   successor or flag a CONFLICT.
5. Facts (FACT items) may only be added with a valid src= pointer.
   You may not paraphrase someone else's FACT without re-verifying.
6. If you cannot satisfy rules 1-5, emit a CONFLICT item and stop.
```

Нарушение этих правил = брак. Pre-commit ловит violations и блокирует
commit с сообщением агенту "regenerate artifact fixing violations".

### 4.6. Conflict marker — explicit blocker

Когда LLM не может продолжать без human-решения:

```markdown
> [!CONFLICT CNF-001] blocks=regeneration
> Conflict between:
>   - spec.md D-012 (locked, human): "timeout = 60s"
>   - impl-plan.md line 42: "timeout = 30s" (from design-agent)
> Cannot regenerate impl-plan without resolving.
> **Options:**
>   (a) change spec D-012 to 30s
>   (b) change impl-plan step 3 to 60s
>   (c) introduce new DECISION that reconciles
> Awaiting human input. Do not auto-resolve.
```

`CONFLICT` — единственный item, который **stops the loop**. Человек
вручную заменяет его на resolution (edit или новый DECISION), после
чего агент может продолжить. Без этого механизма LLM ходит в
бесконечные re-regenerations.

---

## 5. Открытые вопросы

Вопросы, которые стоит закрыть до того, как пилотировать процесс на
реальных тикетах.

- **Budget на iterations.** Сколько раз LLM может перегенерировать
  test-plan без human ack? Без лимита получаем self-improvement петлю
  за токены.
- **Как хранить retrospective при повторяющихся темах.** Если одно и то
  же наблюдение всплывает в пяти ретроспективах подряд — это сигнал
  менять процесс, а не копить заметки. Нужен мелкий механизм
  "promote to process rule".
- **Multi-author locks.** Что если на `D-012 locked=true` претендуют
  двое — автор зафиксировал owner=ek, а тех-лид хочет override'нуть?
  Сейчас owner — поле для blame, не для ACL.
- **Миграция существующих ADR.** В репо могут быть уже написанные
  ADR в старом формате. План миграции: single migration commit,
  все старые ADR → `DECISION` items с ретроспективными ID.
- **Performance collect-items.py на больших тикетах.** На тикетах с
  100+ items регенерация `.index.json` на каждом pre-commit может
  стать заметной. Мерить.
- **Интеграция с Jira/внешним трекером.** Тикеты живут в git, но бизнес
  смотрит в Jira. Нужен one-way sync: git → Jira custom field с
  ссылкой на ветку.

---

> Этот документ покрывает три заданных вопроса. Перед расписыванием
> остальных шагов процесса (детализация Phase 0–6, конкретные промпты
> агентов, pre-commit hooks) стоит зафиксировать именно описанные выше
> механики — они пронизывают весь процесс и изменить их после станет
> существенно дороже.
