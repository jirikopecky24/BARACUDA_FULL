# CLAUDE.md — Barakuda

> Tohle se načítá do KAŽDÉHO promptu v tomto repu. Drž to stručné a jen fakticky
> nutné — cokoliv doménového/postupového patří do `.claude/skills/`, ne sem.
> (Nafouklé CLAUDE.md = platíš tokeny navíc v každém jednom tahu, natrvalo.)

## Co to je
TODO — doplní Claude Code po prozkoumání repa (viz BOOTSTRAP_PROMPT.md).
2–4 věty, jen fakta z kódu, žádné dohady.

## Stack
- Jazyk: Python (doplnit verzi z pyproject.toml / setup.py)
- Klíčové knihovny/framework: TODO
- Testy: TODO (pytest? jiný runner? spouštěcí příkaz?)
- Správa verzí: GitHub, repo `barakuda`
- Lokální cesta: TODO

## Konvence (platí vždy, bez výjimky)
- Type hints všude; žádný `# type: ignore` bez komentáře proč
- Žádné bare `except:` — vždy konkrétní výjimka
- Nové veřejné funkce/třídy/moduly: docstring
- Commit messages: krátce, anglicky, imperativ ("add x", ne "added x")
- Nikdy necommitovat `.env`, secrets, API klíče, tokeny

## Architektura
- Detaily viz `ARCHITECTURE.md` (vytvořit, pokud ještě neexistuje)
- Pořadí implementace/fází viz `BUILD_ORDER.md`
- Stav mezi sezeními viz `HANDOFF.md` — aktualizovat na konci každé delší session

## Subagenti — kdy je použít
- `project-explorer` — orientace v neznámé/velké části kódu, začátek nové session
- `code-reviewer` — po netriviální změně, před commitem
- `test-runner` — po každé změně dotýkající se existující funkcionality
- `domain-check` — TODO, viz BOOTSTRAP_PROMPT.md; smazat, pokud repo doménovou
  kontrolu nepotřebuje

Nespouštět subagenty na triviality (typo, formátování) — zbytečně to násobí tokeny
(subagent v izolovaném kontextu umí spotřebovat řádově víc tokenů než hlavní vlákno).

## Compact instrukce
Při automatické kompresi konverzace vždy zachovat:
- architektonická rozhodnutí a jejich odůvodnění
- otevřené TODO a známé problémy
- poslední stav testů (kolik prochází / kolik padá)
