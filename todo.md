# StatDB — Plan projektu

> **Status:** ✅ Zatwierdzony przez użytkownika (2026-08-27) — decyzje w sekcji 14.
> Fazy realizujemy **sekwencyjnie** (F0 → F15), każda kończy się działającym kodem i testami.

---

## 1. Cel i wizja

**StatDB** to uniwersalna, samohostowana (self-hosted) aplikacja open source do:

1. Definiowania własnych **zbiorów danych** (tabel) o dowolnych kolumnach i typach.
2. Wprowadzania, edycji i przeglądania danych przez GUI.
3. Budowania **widoków** (dashboardów) składających się z konfigurowalnych **widżetów raportowych** (wykresy, KPI, tabele, formularze, filtry).

Aplikacja **nie jest** skupiona na finansach — finanse (zarobki per źródło/miesiąc/rok) to przykładowy, pierwszy przypadek użycia. Silnik ma być w 100% generyczny.

---

## 2. Decyzje technologiczne (propozycje)

| Obszar | Propozycja | Uzasadnienie |
|---|---|---|
| Backend | **Python 3.12 + Quart** (async, ASGI) + Hypercorn | Aplikacja ma działać na serwerze w Dockerze i być dostępna z przeglądarki. **Qt odpada** — to toolkit desktopowy (X11), słabo nadaje się do trybu serwerowego; Quart znasz, jest lekki (Flask-like API, bez narzutu Django/FastAPI). |
| Baza danych | **SQLite** (plik `.db` na wolumenie) przez `aiosqlite` | Zero konfiguracji, backup = kopia pliku, idealne dla self-hosted/open source. Warstwa repozytoriów pozwoli w przyszłości podpiąć PostgreSQL (roadmap). |
| Fizyczny model danych | **Dynamiczne, fizyczne tabele SQL** per zbiór + katalog metadanych | Każdy zbiór użytkownika to prawdziwa tabela (`data_<slug>`) z typowanymi kolumnami → natywne `GROUP BY`/`SUM`/`AVG` bez kombinowania (inaczej niż EAV). Katalog opisuje schematy, etykiety, opcje, kolory. |
| Frontend | **Jinja2 (Quart) + vanilla JS** | Bez ciężkiego SPA — prosty w utrzymaniu open source, szybki start. |
| Wykresy | **Apache ECharts** (vendored lokalnie w `static/`, bez CDN) | Słupkowe, stacked (wieloelementowe), liniowe, kołowe, heatmapy; świetne tooltips i skalowanie; działa offline. |
| Układ dashboardu | **gridstack.js** (vendored) | Drag & drop + zmiana rozmiaru widżetów na siatce 12-kolumnowej. |
| Testy | `pytest` + `pytest-asyncio` | Testy warstwy DB, agregacji i API. |
| Kontener | `Dockerfile` (non-root, slim) + `docker-compose.yml` | Wolumen na katalog `data/` (baza SQLite), konfiguracja przez zmienne środowiskowe, healthcheck. |

**Bezpieczeństwo SQL:** identyfikatory (nazwy tabel/kolumn) zawsze bierzemy z whitelisty katalogu i walidujemy regexem; wartości wyłącznie jako parametry zapytań.

---

## 3. Struktura projektu

```
StatDB/
├── app/
│   ├── __init__.py          # fabryka aplikacji Quart
│   ├── config.py            # konfiguracja ze zmiennych środowiskowych
│   ├── db.py                # warstwa SQLite (aiosqlite), migracje katalogu
│   ├── catalog/             # zbiory + kolumny: metadane, dynamiczne tabele
│   ├── rows/                # CRUD wierszy + walidacja typów
│   ├── aggregation/         # silnik agregacji (sum/avg/count/min/max/median, group-by, series, filtry)
│   ├── views/               # widoki i widżety: persistence + logika
│   ├── api/                 # REST API (blueprint)
│   ├── web/                 # strony HTML (blueprint)
│   ├── auth/                # sesje, hasło, linki publiczne
│   ├── i18n/                # PL / EN
│   ├── templates/
│   └── static/              # vendored ECharts/gridstack + własne css/js
├── tests/
├── data/                    # katalog na bazę SQLite (wolumen w Dockerze)
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
├── README.md
├── LICENSE
└── todo.md                  # ten plik
```

---

## 4. Model danych

### 4.1 Katalog (metadane — stały schemat, migracje)

- `datasets` — id, slug, nazwa, opis, data utworzenia
- `columns` — id, dataset_id, klucz, etykieta, **typ**, config JSON, kolejność
- `views` — id, nazwa, ikona, motyw, ustawienia JSON
- `widgets` — id, view_id, typ, tytuł, config JSON, pozycja/rozmiar (x, y, w, h)
- `settings` — globalne preferencje (język, motyw, waluta domyślna)

### 4.2 Typy kolumn

| Typ | Opis |
|---|---|
| `text` | dowolny tekst |
| `integer` | liczby całkowite |
| `float` | liczby dziesiętne (np. kwota) |
| `bool` | tak/nie |
| `date` | **data krótka** — miesiąc liczbowy (np. 27.08.2026; separator/format konfigurowalny) |
| `date-long` | **data długa** — miesiąc słowny (np. 27 sierpnia 2026 PL / August 27, 2026 EN; format konfigurowalny, miesiąc wg języka UI) |
| `datetime` | data + czas (np. 27.08.2026 14:30) |
| `year` | sam rok (np. 2026) |
| `year-month` | para rok–miesiąc (np. 04-2026; sortowanie chronologiczne, format konfigurowalny) |
| `select` | **lista opcji: klucz porządkujący + etykieta + opcjonalny kolor** |
| `currency` | float + kod waluty + formatowanie wyświetlania |
| `formula` | kolumna wyliczana z innych (np. suma dwóch kolumn) |

### 4.3 Wiersze

Dane użytkownika trzymane w fizycznych tabelach `data_<slug>` tworzonych/migrowanych automatycznie przy zmianach schematu (dodanie/usunięcie/zmiana typu kolumny → `ALTER TABLE` lub bezpieczna przebudowa).

---

## 5. Sortowanie i etykiety miesięcy (wymaganie kluczowe)

- Typ `select` przechowuje **klucz** (liczba/string) i **etykietę** osobno.
- **Sortowanie zawsze po kluczu** (miesiące 1→12 rosnąco), a **wyświetlanie zawsze po etykiecie**.
- Preset **„Miesiące"** tworzy od razu opcje `1..12` z etykietami zgodnymi z językiem UI (PL: „Styczeń…Grudzień", EN: „January…December").
- W wykresach kategorie osi X dostają etykiety z mapowania klucz→etykieta; kolejność nigdy nie jest alfabetyczna.
- Ten sam mechanizm działa dla dowolnych porządkowych kategorii użytkownika (np. s, m, l, xl rozmiary).
- Typy `year` i `year-month` sortują się naturalnie chronologicznie; `year-month` wyświetla się np. jako „04-2026" (format w konfiguracji kolumny).

---

## 6. Widżety

### Podstawowe (wymagane)

1. **Tabela danych** — podgląd wierszy, edycja inline, usuwanie, sortowanie, filtry kolumn, paginacja.
2. **Formularz wstawiania** wartości (widżet „dodaj rekord" dla wybranego zbioru, walidacja typów).
3. **Wykres słupkowy** — jedna seria: agregacja (sum/avg/count/…) per kategoria.
4. **Wykres słupkowy wieloelementowy (stacked)** — kategoria × seria (np. rok × źródło), kolory segmentów per seria.
5. **KPI „Suma"** — duża liczba z formatem.
6. **KPI „Średnia"** — duża liczba z formatem.

### Dodatkowe (kreatywne, użyteczne)

7. **KPI: Min / Max / Liczba wierszy / Mediana**.
8. **Wykres liniowy** — trendy w czasie.
9. **Wykres kołowy / donut** — udziały procentowe (np. udział źródeł w roku).
10. **Tabela agregująca** („suma per grupa") — tekstowe zestawienie sum/średnich per dowolny wymiar, z wierszem „Ogółem" (to pokrywa Twoje tekstowe sumy roczne/miesięczne ogólne i per źródło).
11. **KPI trend** — wartość + delta i strzałka ↑/↓ vs poprzedni okres (np. ten rok vs zeszły).
12. **Widżet filtra globalnego widoku** — wybór roku/źródła/zakresu dat filtruje wszystkie widżety na dashboardzie.
13. **Notatka tekstowa (Markdown)** — opisy na dashboardzie.
14. **Heatmapa** — np. intensywność miesiąc × rok.

### Konfiguracja każdego widżetu

`dataset`, typ agregacji, kolumna wartości, group-by (oś X), series-by (segmenty), filtry, sortowanie, tytuł, paleta/kolory, format liczb (miejsca dziesiętne, separator, prefiks/sufiks), wysokość (dla wykresów).

---

## 7. Mapowanie Twojego przypadku użycia

Zbiór **„Zarobki"**: `rok` (integer), `miesiąc` (select 1–12, etykiety PL), `źródło` (select + kolory), `kwota` (float/currency PLN).

| Chcesz zrobić | Widżet |
|---|---|
| Słupkowy sum zarobków per rok, segmenty = źródła (kolory) | #4 stacked bar (group-by: rok, series: źródło) |
| Słupkowy średniej zarobków per rok | #3 bar (agregacja AVG, group-by: rok) |
| Słupkowy średniej zarobków per miesiąc | #3 bar (AVG, group-by: miesiąc — sort 1–12, etykiety nazw) |
| Tekstowe sumy roczne/miesięczne, ogólne i per źródło | #10 tabela agregująca (wymiary: rok / miesiąc × źródło) + KPI #5 |

Wszystko powyższe to **konfiguracja** (kilka kliknięć), nie kod — silnik jest generyczny.

---

## 8. Customizacja

- **Motywy:** jasny / ciemny + kolor akcentu; palety wykresów do wyboru; kolor per opcja select (np. kolor źródła przychodu).
- **Dashboard:** drag & drop, zmiana rozmiaru, wiele widoków (zakładki), widok domyślny.
- **Formatowanie liczb:** miejsca dziesiętne, separator tysięcy, waluta/sufiks.
- **i18n:** domyślnie **EN**, przełącznik na **PL**; język można też wymusić zmienną środowiskową (`STATDB_LANGUAGE=en|pl`).
- Własny CSS wstrzykiwany do widoku, auto-refresh widżetów (tryb TV/kiosk), eksport wykresu do PNG (przycisk na widżecie).

---

## 9. Autoryzacja i bezpieczeństwo

- **Single-user, hasło opcjonalne:** jeśli ustawiono `STATDB_PASSWORD` — logowanie + sesja cookie; jeśli nie ustawiono — instancja działa **bez hasła** (tryb trusted).
- CSRF na formularzach, parametryzowane zapytania, whitelist identyfikatorów, limit paginacji.
- Publiczne linki read-only do widoku (token w URL), tokeny API do integracji zewnętrznych.
- **(roadmap)** multi-user + role.

---

## 10. Import / eksport / backup

- Import **CSV** z mapowaniem kolumn, podglądem i raportem błędów walidacji.
- Eksport zbioru do **CSV/JSON**.
- Backup całej bazy (pobranie pliku `.db`) + eksport/import **konfiguracji widoków** (JSON) — przenoszalność między instancjami.
- Zaplanowane snapshoty bazy z retencją (np. codziennie, trzymaj N ostatnich).

---

## 11. REST API (szkic)

```
GET/POST        /api/datasets                 # lista / utwórz zbiór
GET/PATCH/DELETE /api/datasets/<slug>         # schemat zbioru
GET/POST        /api/datasets/<slug>/rows     # wiersze (filtry, paginacja)
PATCH/DELETE    /api/datasets/<slug>/rows/<id>
POST            /api/aggregate                # silnik agregacji (dla widżetów)
GET/POST        /api/views                    # widoki
POST/PATCH/DELETE /api/views/<id>/widgets     # widżety
GET             /api/i18n/<lang>              # słowniki
```

---

## 12. Fazy realizacji (sekwencyjne)

- [x] **F0** ✅ (2026-08-27) — Scaffold: struktura katalogów, `pyproject.toml`, fabryka Quart, config z env, logger, „hello" + smoke test. Mechanizm i18n: EN domyślnie, przełącznik PL (cookie), wymuszenie przez `STATDB_LANGUAGE`.
- [x] **F1** ✅ (2026-08-27) — Warstwa DB: `aiosqlite` (FK + WAL na każdym połączeniu), runner migracji katalogu (`schema_migrations` + `PRAGMA user_version`, embedded SQL w `app/migrations/`), healthcheck `/api/healthz`. Schemat katalogu: datasets, columns, views, widgets, settings, share_links, api_tokens.
- [x] **F2** ✅ (2026-08-27) — Katalog zbiorów: wszystkie typy kolumn (w tym warianty dat oraz `currency`/`formula`), dynamiczne tabele fizyczne `data_<slug>` (bazowe metadane + shadow pola jak `month__sort_key`), preset „Miesiące" (generator year-month/sup fill), REST API schematów (`/api/datasets`, kolumny, preset). USER_VERSION=2, migracja 002 (indeksy dla lookupów).
- [x] **F3** ✅ (2026-08-27) — CRUD wierszy z pełną walidacją typów (Python-side validators per typ: normalizacja ISO/`MM-YYYY`, sort-key dla year-month, select sprawdza klucze opcji), bezpieczny silnik formuł (`ast`, whitelista węzłów + `round/abs/min/max`, `{col}` lub bare name), CRUD z shadow-fieldami i auto-rekalkulacją formuł, API rows z filtrami (`?f.<col>.<op>=` — eq/ne/lt/lte/gt/gte/contains), sortowaniem (`?sort=±<col>`, year-month po `__sort_key`) i paginacją (page/page_size ≤ 500, `total` w odpowiedzi).
- [x] **F4** ✅ (2026-08-28) — Silnik agregacji (sum/avg/count/min/max/median [Python], group-by + series [stacked], filtry eq/ne/lt/lte/gt/gte/contains/in/year, sortowanie select wg kolejności opcji config i year-month po `__sort_key`, etykiety i kolory select per język en/pl). Filtry year-month porównują wartości na cieniu `__sort_key` (normalizacja MM-YYYY→YYYYMM), `contains` na tekście display. `POST /api/aggregate` + 12 testów.
- [x] **F5** ✅ (2026-08-28) — Widoki i widżety: persistence + API (ViewStore: CRUD widoków + widżetów, walidacja typów WIDGET_TYPES [16 typów], geometria gridstack x/y/w/h na siatce 12-kol z walidacją x+w≤12, auto position = MAX+1, set_layout bulk z kontrolą własności, kaskada FK przy usuwaniu widoku; REST: GET/POST /api/views, GET/PATCH/DELETE /views/<id> [GET zagnieżdża widgets], GET/POST /views/<id>/widgets, PUT /views/<id>/layout, PATCH/DELETE /widgets/<id>; KeyError→404, ValueError→400; 9 testów).
- [x] **F6** ✅ (2026-08-28) — Frontend: layout bazowy (base.html: nawigacja, stopka, i18n EN/PL + przełącznik), motywy jasny/ciemny + 3 akcenty (niebieski/zielony/bursztyn, localStorage, skrypt pre-CSS bez migotania), strona zbiorów (lista kart + formularz tworzenia + preset „Miesiące”), strona zbioru z edytorem schematu kolumn (edycja label/config inline, dodawanie/usuwanie kolumn z potwierdzeniem, typ read-only, preset kolumny „month” year-month MM-YYYY), routes POST formularzy (redirect, walidacja slug lowercase, JSON config), strona główna z CTA do zbiorów, fix kolizji nazwy `key` w t(); 7 testów web (suite 77 green).
- [x] **F7** ✅ (2026-08-28) — UI tabeli danych: sekcja „Dane" na stronie zbioru z edycją inline komórek (widget wg typu: text/number step=1|any/date/datetime-local/year-month placeholder/checkbox bool/select z opcji config, formuły read-only; formularze spięte atrybutem HTML `form=`, bez JS), wiersz dodawania rekordu na końcu tabeli, usuwanie z potwierdzeniem JS, licznik rekordów, stan pusty „najpierw dodaj kolumny", koercja wartości formularza → walidatory rows (przecinek dziesiętny `12,5` → `12.5`, puste pole → NULL, bool z checkboxa), 3 endpointy POST (create/update/delete; ValueError → redirect bez zmian, KeyError → 404), makro `_macros.field` + klasa `.table` generyczna (schema-table zunifikowana), 5 kluczy i18n; limit 500 wierszy na stronie; 3 testy web (suite 80 green).
- [x] **F8** ✅ (2026-08-28) — Dashboard: strony widoków (lista + tworzenie + szczegół), vendorowany minimalny gridstack (własny `gridstack.js` + `gridstack.min.css`, siatka 12 kolumn), drag & drop i resize narożnikiem z autozapisem układu (debounced fetch → POST /layout z JSON, KeyError → 400), dodawanie widżetu (typ + tytuł + zbiór/kolumna opcjonalne), edycja tytułu i configu JSON (sekcja inline otwierana ✎, submit przez fetch z podmienionym id w URL), usuwanie z potwierdzeniem (`data-confirm-delete` z tytułem), placeholder renderera F9, link „Widoki” w nav, 20 kluczy i18n `views.*` EN/PL; naprawiona trasa `GET /datasets` nadpisana wcześniej; 3 testy web (suite 83 green).
- [x] **F9** ✅ (2026-08-28) — Renderery widżetów (`widget_renderers.js`, 430 linii IIFE): notatka (text z config), KPI sum/avg/min/max/count/median (scalar+grouped, formatowanie liczb), KPI trend (delta % z strzałką ▲▼), bar (DOM, sort po wartości), stacked_bar (DOM, segmenty po serii z kolorami), line (SVG polyline + osie), pie (SVG arcs), heatmap (SVG rect grid), agg_table (DOM table z kolumnami series), global_filter (input+OK → `window.StatDBFilter` → re-render); pełna obsługa odpowiedzi API (scalar/grouped/stacked) z `fetchAggregate` (inject globalnego filtra do `filters`), eksport PNG (SVG→canvas→toDataURL→download), przycisk ⬇ dodawany do nagłówka dla SVG widgetów; CSS F9 w `app.css` (`.widget-note`, `.widget-kpi*`, `.widget-bars`, `.bar-*`, `.widget-line/pie/heatmap`, `.widget-agg-table`, `.widget-gfilter`, `.widget-export`); naprawiony `aggregate.py` (KeyError/TypeError→400), rozdzielony placeholder/body w `view_detail.html`; 7 testów web (markup, note, KPI z dataset, placeholder bez dataset, aggregate smoke/stacked/errors) + helper `_seed_dataset` (suite 90 green).
- [x] **F10** ✅ (2026-08-28) — Import CSV (wykrywanie typów kolumn z regex: bool/year-month/year/date/datetime/integer/float/text, sanityzacja kluczy, deduplikacja), eksport CSV/JSON zbioru (`GET /api/datasets/<id>/export?format=` + web `/datasets/<id>/export`), backup bazy (`VACUUM INTO` + `GET /api/backup` + web `/backup`), eksport/import konfiguracji widoków (`GET /api/views/export` → JSON `{version, views:[...]}`, `POST /api/views/import` z body lub plikiem), zaplanowane snapshoty z retencją (`app/snapshots.py`: scheduler asyncio loop, env `STATDB_SNAPSHOT_ENABLED/INTERVAL/RETENTION`, `VACUUM INTO` snapshot, automatyczne prunning stare, API CRUD `/api/snapshots/*`), strona transferu (`/transfer` z formularzami import CSV, backup, eksport/import widoków, lista snapshotów), schedulery snapshotów uruchamiane w `create_app` via `before_serving`, 30 kluczy i18n `transfer.*` EN/PL, link w nav; 11 testów (import CSV, export CSV/JSON, backup, views export/import API+web, transfer page, snapshot create/list/delete, snapshot trigger web).
- [x] **F11** ✅ (2026-08-28) — Auth: opcjonalne hasło z env (`STATDB_PASSWORD`), login/logout (session cookie, `hmac.compare_digest`), tokeny API (`STATDB_API_TOKEN`, bearer auth na `/api/*`), publiczne linki read-only (`/public/views/<id>` bypass auth), gatekeep middleware (`before_app_request`: redirect dla web, 401 JSON dla API), i18n domyślnie EN z przełącznikiem PL (cookie), wymuszenie przez `STATDB_LANGUAGE` env var, 12 kluczy i18n `auth.*` EN/PL; 7 testów (no-password open, login flow, API token, API+password, public view bypass, logout, healthz no-auth).
- [x] **F12** ✅ (2026-08-28) — Dockerfile (python:3.12-slim, non-root user `statdb` uid 1000, healthcheck na `/api/healthz`, `hypercorn run:app`), docker-compose.yml (port/env passthrough, volume `./data:/app/data`), `.dockerignore` (build cache/snapshots/tests/docs excluded), `data/.gitkeep` dla pustego wolumenu; app auto-tworzy `data/` + migracje na pierwszym requeście — pusty mount działa out-of-the-box.
- [x] **F13** ✅ (2026-08-28) — README (EN, pełna dokumentacja: features, quick start Docker+dev, config table, API overview, tech stack), CHANGELOG.md (Keep a Changelog format, F0-F13), LICENSE MIT (już istniał).
- [x] **F14** ✅ (2026-08-29) — Testy e2e kluczowych flow: 5 testów (dataset→columns→rows→aggregate sum+grouped, view→3 widgets→dashboard render→layout persist, CSV import→export round-trip, public view access, backup+views export/import round-trip); fix export endpoint (page_size>500 paginated loop). Suite 112 green.
- [x] **F15** ✅ (2026-08-29) — Custom CSS per widok (textarea w ustawieniach widoku, wstrzykiwany `<style id="view-custom-css">` do view_detail + public_view), auto-refresh widżetów (interval re-render z ustawień `settings.refresh`, 0=wył), tryb TV/kiosk (przycisk 📺 + checkbox w ustawieniach, fullscreen API, ukrycie nav/footer/formularzy/edycji, Escape=wyjście, URL `?kiosk=1` dla public view); POST `/views/<id>/settings`, 9 kluczy i18n `views.*` EN/PL, 9 testów (settings save/defaults, CSS injection view+public, no-CSS guard, kiosk button, kiosk URL param, auto-refresh interval, form fields); suite 121 green.

---

## 13. Roadmap (poza MVP)

PostgreSQL jako backend, multi-user z rolami, raporty e-mail cykliczne, widgety-pluginy (rejestracja własnych typów), osadzanie wykresów iframe, aplikacja mobilna / PWA offline-first.

---

## 14. Decyzje zatwierdzone (2026-08-27)

1. **Stos:** Quart + SQLite + Jinja2/vanilla JS + ECharts + gridstack.js — ✅ zatwierdzony.
2. **Licencja:** MIT — ✅ zatwierdzona.
3. **Język UI:** domyślnie **EN**, przełącznik na PL, możliwość wymuszenia przez zmienną środowiskową (`STATDB_LANGUAGE=en|pl`).
4. **Autoryzacja:** hasło **opcjonalne** — gdy `STATDB_PASSWORD` nie jest ustawione, instancja działa bez logowania (tryb trusted).
5. **Zakres MVP rozszerzony:** realizujemy **wszystko** z sekcji 4–12 (w tym `currency`, `formula`, KPI trend, heatmapę, publiczne linki read-only, tokeny API, snapshoty z retencją, custom CSS, auto-refresh/kiosk, eksport PNG). Poza zakresem pozostaje wyłącznie sekcja 13 „Roadmap (poza MVP)".
6. **Typy dat (5):**
   - `date` — **krótka**: miesiąc liczbowy (np. 27.08.2026),
   - `date-long` — **długa**: miesiąc słowny (np. 27 sierpnia 2026 / August 27, 2026; słownik miesięcy wg języka UI),
   - `datetime` — data + czas (np. 27.08.2026 14:30),
   - `year` — sam rok (np. 2026),
   - `year-month` — para rok–miesiąc (np. 04-2026; sortowanie chronologiczne).
   Wszystkie sortują się po rzeczywistej wartości, a nie po sformatowanym tekście.

**Plan zatwierdzony — realizacja od F0.**


## 15. Sprawy do naprawy, wpisane przez użytkownika

> **Status:** ✅ Wszystkie 21 punktów naprawione.
> 1. ✅ Language switcher — cookie zapisywany, ikona poprawiona (prior session).
> 2. ✅ Usunięto wszystkie presety (datasets + column). year-month pozostaje jako typ kolumny w dropdownie.
> 3. ✅ Usunięto surowy "Config (JSON)" — zastąpiono intuicyjnym GUI per typ kolumny.
> 4. ✅ Select options konfigurowane przez GUI (dodawanie/usuwanie/przesuwanie, color picker, opcjonalne tłumaczenia EN/PL).
> 5. ✅ Domyślnie pojedynczy label (string) dla każdej opcji; EN/PL jako opcjonalne tłumaczenia (toggle)
> 6. ✅ Widget type names — przyjazne przetłumaczone nazwy (`views.wtype.*`, EN+PL) w dropdownie tworzenia/edycji oraz w nagłówkach widżetów, zamiast surowych kodów typów.
> 7. ✅ Usuwanie całego widoku — przycisk „Usuń widok" z potwierdzeniem na liście widoków i stronie widoku (POST `/views/<id>/delete`, 404 dla brakującego, kaskadowe usunięcie widżetów).
> 8. ✅ Nowe widżety lądują w pierwszym wolnym miejscu siatki (serwerowy `_free_slot`), zamiast nachodzić na istniejące; jawnie podane x/y nadal respektowane.
> 9. ✅ Widget `table` ma pełny renderer — tabela danych z kolumnami zbioru (etykiety select, ✓/✗ dla boolean), paginacja „{shown} z {total} wierszy"; dodany też renderer `form` (dodawanie rekordów z widoku).
> 10. ✅ Heatmapa — dodane pole `series` do reguł konfiguracji oraz graceful fallback `grouped → stacked`; wyraźny komunikat „Brak danych do wyświetlenia…" zamiast mylącego „Configure this widget".
> 11. ✅ Wykres liniowy — pełny renderer: poziome linie siatki z etykietami wartości, etykiety osi X, punkty z tooltipami, legenda grup/kolorów (multi-series).
> 12. ✅ Grupowanie złożone — `group_by` przyjmuje listę kolumn + drugi poziom „Grupuj wg (2. poziom)" w GUI widżetów; silnik agregacji obsługuje buckety złożone (np. rok + miesiąc select → chronologiczna oś miesiąc+rok; kolumny temporalne sortowane w pierwszej kolejności po stronie klienta).
13. ✅ Pionowe warianty wykresów słupkowych — nowe typy widżetów `bar_vertical` i `stacked_bar_vertical` (styl Excela: etykiety na dole, pionowe słupki, automatycznie wyliczane checkpointy wartości w legendzie po lewej).
14. ✅ Etykiety zgrupowania — `text-overflow: ellipsis` + `title` z pełnym tekstem (tooltip na hover), kolumna etykiet bierze tyle miejsca, ile potrzebuje.
15. ✅ Sortowanie wyników — pola "Sortuj według" (domyślna kolejność / etykiety zgrupowania A→Z / wartość miary) i "Rosnąco/Malejąco" w GUI dodawania i edycji widżetu (`sort_by`/`sort_dir` w config, sortowanie po stronie klienta; "default" = zachowanie sprzed zmiany).
16. ✅ Usuwanie i rename widoku schowane za menu ⋯ (`details.card-menu`) na liście widoków + rename też w nagłówku strony widoku (POST `/views/<id>/rename`).
17. ✅ Add widget jako modal — `widget-create-modal` nad siatką z przyciemnionym tłem (`modal-overlay`), zamykany kliknięciem w tło / ✕ / Esc.
18. ✅ Edit widget jako modal — `widget-edit-modal` działa identycznie jak Add widget (pkt 17).
19. ✅ View settings jako modal — `view-settings-modal` otwierany przyciskiem ⚙ w toolbarze.
20. ✅ Wykresy SVG (line/pie/heatmap/słupki pionowe) skalują się do rozmiaru widżetu — `flex: 1` w `.widget-body` zamiast stałego `max-height: 240px`; zawartość viewBox rośnie proporcjonalnie z widżetem.
21. ✅ Heatmapa i line chart — renderery są teraz świadome rozmiaru kontenera (`bodySize`): line chart renderuje się dokładnie w wymiarach ciała widżetu (a przy wielu punktach trzyma min. 34px/pkt i przewija poziomo), heatmapa skaluje się w górę gdy jest miejsce, ale nigdy poniżej naturalnego rozmiaru (czytelne komórki) — nadmiar przewija się w ciele widżetu (`overflow: auto`). Dodany `ResizeObserver` (debounce 200ms, tylko typy `line`/`heatmap`) przerenderowuje wykres po zmianie rozmiaru widżetu. Później ten sam mechanizm rozszerzony na pionowe słupki (`bar_vertical`/`stacked_bar_vertical`): wypełniają widżet, trzymają min. 30px/słupek (nadmiar → scroll poziomy), etykiety osi X przerzedzane wg faktycznej szerokości słupka, re-render po resize.