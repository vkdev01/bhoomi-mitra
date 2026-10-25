# Bhoomi Mitra

A multilingual, agentic civic-information assistant built on **ISRO / NRSC Bhuvan** open data and **Sarvam AI**.

Ask a question in your own language — by voice or text — about any village: what the land is used for, where the nearest hospital or post office is, and how far away it is. An LLM decides which ISRO data services to call, calls them, and answers in plain language.

```
"Tell me about Sekuru — what is the land used for, and how far is the nearest hospital?"

→ Sekuru, Guntur, Andhra Pradesh. Population 10,207. Land cover around it (2015_16) is
  mainly Agricultural land 80%, Built-up land 11%, Water bodies 6%. Nearest hospital:
  Primary Health Centre, Chebrolu, about 0.7 km away. (Source: ISRO Bhuvan.)
```

---

## Why this exists

Most Indian citizens who need land-use or public-facility information do not get it from a GIS portal. They ask someone. The two hard parts of changing that are language and data plumbing — and both are now tractable: Sarvam handles Indian-language speech and text, and Bhuvan publishes the geospatial services.

This project is the integration layer: an agent that turns a spoken question into a sequence of official-data lookups and a spoken answer.

---

## What it actually does

**Agentic question answering.** The model is given four tools and decides which to call:

| Tool | Backed by | Returns |
|---|---|---|
| `resolve_place` | Bhuvan village geocoding | Census name, district, state, population, households, coordinates |
| `land_cover` | Bhuvan LULC statistics | Area and percentage per land-use class |
| `nearby_facilities` | Bhuvan proximity | Hospitals and post offices, nearest first |
| `route_to_facility` | Bhuvan shortest-path | Road distance, duration, GeoJSON geometry |

The loop is bounded, traced, and shown in the UI ("what the assistant did"), so an answer is auditable rather than a black box.

**Village profile.** A deterministic endpoint that assembles the same data into a structured report — no LLM in the path, so it is fast, free and reproducible.

**Voice.** Speech-to-text (Saaras), the agent loop, then text-to-speech (Bulbul) played back in the browser. In a regional language end to end.

---

## Quickstart

Runs immediately with **no API keys**. It falls back to bundled sample data and a deterministic offline planner, so you can see the whole system work before signing up for anything.

```bash
git clone https://github.com/vkdev01/bhoomi-mitra.git
cd bhoomi-mitra
pip install -r requirements.txt
python main.py            # → http://localhost:8000
```

Verify it:

```bash
python -m pytest          # 136 tests
python scripts/smoke_test.py   # boots a real server and exercises every endpoint
```

### Turning on live data

Copy `.env.example` to `.env` and fill in whichever credentials you have. Each one upgrades one layer independently.

| Variable | What it unlocks | Where to get it |
|---|---|---|
| `BHUVAN_TOKEN` | Live ISRO Bhuvan data instead of sample fixtures | [bhuvan-app1.nrsc.gov.in/api](https://bhuvan-app1.nrsc.gov.in/api/) — register, then "Get Access Token" per theme |
| `SARVAM_API_KEY` | Sarvam-105B for the agent, plus voice in and out | [dashboard.sarvam.ai](https://dashboard.sarvam.ai) |

`BHOOMI_DATA_MODE` controls this explicitly: `auto` (default — live where credentials exist), `live` (force live), `fixture` (force sample data).

The UI always shows which mode is active, so an answer is never mistaken for live data when it isn't.

---

## Architecture

Hexagonal (ports and adapters). The dependency arrows all point inwards: the domain knows nothing about HTTP, FastAPI, Bhuvan or Sarvam.

```
                    ┌──────────────────────────────┐
   browser  ───────▶│  web/  FastAPI + static UI   │  DTOs, error mapping
                    └──────────────┬───────────────┘
                                   │ calls use cases
                    ┌──────────────▼───────────────┐
                    │  application/                │
                    │   BuildVillageReport         │  orchestration,
                    │   AskAssistant (agent loop)  │  no I/O of its own
                    │   ToolRegistry               │
                    └──────────────┬───────────────┘
                                   │ depends only on Protocols
                    ┌──────────────▼───────────────┐
                    │  domain/                     │  entities, value objects,
                    │   models · ports · messages  │  errors, LULC legend
                    │   lulc · errors              │  ZERO dependencies
                    └──────────────▲───────────────┘
                                   │ implements
                    ┌──────────────┴───────────────┐
                    │  adapters/                   │
                    │   bhuvan · fixtures          │  HTTP, parsing,
                    │   sarvam · offline_llm       │  error translation
                    │   http                       │
                    └──────────────────────────────┘
                                   ▲
                    ┌──────────────┴───────────────┐
                    │  composition.py              │  the ONLY place that
                    │  (composition root)          │  names a concrete class
                    └──────────────────────────────┘
```

### How SOLID shows up here

| Principle | Where you can see it |
|---|---|
| **S**ingle Responsibility | `bhuvan.py` holds four separate classes — geocoding, facilities, routing, LULC — sharing one client but no behaviour. `web/presenters.py` maps domain→DTO so routes never format. `domain/lulc.py` owns the legend so a code rename touches one file. |
| **O**pen/Closed | Adding a data source or a new agent tool means implementing a port or calling `registry.register(...)`. Neither `AskAssistant` nor `BuildVillageReport` changes. Adding MOSDAC weather is a new adapter, not an edit. |
| **L**iskov Substitution | `tests/test_contracts.py` runs **the same assertions** against the fixture provider and the real Bhuvan adapters over a stub transport. Substitutability is tested, not asserted in a comment. |
| **I**nterface Segregation | Ports are narrow and separate: `PlaceResolver`, `LandCoverProvider`, `FacilityProvider`, `RouteProvider`, `LanguageModel`, `SpeechTranscriber`, `SpeechSynthesizer`, `Translator`. A test double implements only what it needs; a routing-only consumer never sees LULC code. |
| **D**ependency Inversion | `application/` imports only `domain.ports` (Protocols). `adapters/` import the domain. `composition.py` is the single module that chooses a concrete class, which is what makes `BHOOMI_DATA_MODE=fixture` a one-line switch. |

Two supporting habits worth noting: adapters translate every transport failure into a domain error (`UpstreamAuthError`, `UpstreamUnavailableError`), so use cases never catch `httpx` exceptions; and `BuildVillageReport` degrades — a routing outage records a note and still returns land cover.

---

## API

Interactive docs at `/docs`. Full schema at `/openapi.json`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness + active data source |
| `GET` | `/api/config` | Active sources, languages, sample places. Never exposes secrets |
| `POST` | `/api/village/report` | Structured profile — `{place}` or `{lat, lon}`, plus `radius_m`, `year`, `include_routes` |
| `POST` | `/api/assistant/ask` | Agentic answer — `{question, language_code, place?}` |
| `POST` | `/api/assistant/voice` | Multipart audio → transcript, answer, and synthesized speech (503 without a Sarvam key) |

```bash
curl -X POST localhost:8000/api/village/report \
  -H 'Content-Type: application/json' \
  -d '{"place": "Sekuru", "radius_m": 20000}'
```

---

## Project layout

```
src/bhoomi/
  domain/         models.py  ports.py  messages.py  lulc.py  errors.py
  application/    village_report.py  assistant.py  tools.py  tool_registry.py
  adapters/       bhuvan.py  fixtures.py  sarvam.py  offline_llm.py  http.py
  web/            app.py  routes.py  schemas.py  presenters.py  static/index.html
  composition.py  config.py
fixtures/         demo_geo.json
tests/            domain · adapters · contracts · use cases · agent loop · API
scripts/          smoke_test.py
```

---

## Data sources, attribution and honest caveats

**Bhuvan** (ISRO / National Remote Sensing Centre) — village geocoding, LULC statistics, proximity and routing services. Free for use with a token.

**Sarvam AI** — Sarvam-105B for reasoning and tool calling, Saaras for speech-to-text, Bulbul for text-to-speech, Mayura for translation.

Things you should know before relying on this:

- **The sample data is sample data.** `fixtures/demo_geo.json` exists so the app runs without a token. It mirrors Bhuvan's response *shapes*; the figures are illustrative, not authoritative. The UI labels it "sample data". Set `BHUVAN_TOKEN` for real answers.
- **Coverage is not national.** As documented, Bhuvan's hospital/postal proximity and village geocoding services cover **Andhra Pradesh and Karnataka**. Other states will return no data. Routing is intra-state only.
- **LULC scale is a choice.** 1:50,000 (`BHUVAN_LULC_SCALE=50k`) is finer but single-epoch; 1:250,000 (`250k`, the default) supports year-over-year queries.
- **The offline planner is not the LLM.** With no Sarvam key, `RuleBasedLanguageModel` keyword-matches a place and calls tools deterministically. It exercises the loop; it does not understand language. The UI says so.
- **Bhuvan's response field names drift.** The mappers accept documented aliases and fail loudly rather than guessing — check `tests/test_bhuvan_adapter.py` when a mapping breaks.
- **NavIC/GAGAN is not a public API.** Signal data comes through a research Announcement of Opportunity, so this project does not use it.

---

## Testing

```bash
python -m pytest                     # 136 tests, ~1.5 s, no network
python -m pytest tests/test_contracts.py -v   # substitutability, both adapters
python scripts/smoke_test.py         # 15 end-to-end checks against a real server
ruff check src tests
```

The suite never touches the network: Bhuvan is exercised through `httpx.MockTransport` and the LLM through the offline planner.

---

## Roadmap

- MOSDAC weather and ocean forecasts as additional tools (a new adapter + a `registry.register` call)
- Bhoonidhi STAC search for satellite imagery alongside the statistics
- WhatsApp / IVR channel, so the voice pipeline reaches feature phones
- Response caching keyed on rounded coordinates, to stay inside Bhuvan's rate limits

---

## License

MIT — see [LICENSE](LICENSE).

Built by [Vaibhav Kumar](https://github.com/vkdev01). Data © ISRO/NRSC Bhuvan; speech and language models © Sarvam AI.
