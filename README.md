# Berlin Marathon — privacy-first dashboard

Static Wasmer dashboard generated from local CSV inputs.

## What changed

- The public dashboard no longer downloads runner-level CSVs from GitHub.
- `scripts/prepare_data.py` reads the private/raw CSVs locally and writes aggregate JSON into `public/data/<year>/dashboard.json`.
- Generated public JSON is automatically rejected if it contains keys such as `Name`, `RunnerID`, or `BibNumber`.
- The redesign adds pacing, late-race slowdown, split strategy, demographics, countries, weather, Boston-standard context, and 2024/2025 comparison.
- Original HTML files are retained in `backup/` only. Wasmer serves only `public/`.

## Build the public data

From the project directory:

```powershell
py .\scripts\prepare_data.py
```

Expected output includes:

```text
Wrote public/data/2025/dashboard.json
Wrote public/data/2024/dashboard.json
Privacy validation passed
```

## Preview locally

```powershell
py -m http.server 8000 --directory public
```

Open `http://localhost:8000`.

## Deploy

The existing `wasmer.toml` still serves the `public` directory, so the Wasmer deployment model is unchanged. Run the preprocessing step before publishing whenever the source CSVs change.

## Privacy model

Keep the raw `support/` CSVs private. Only deploy the `public/` directory/package output. The public JSON contains aggregate counts and derived statistics, not runner names, runner IDs, or bib numbers.

`index_2024.html` and `index_compare.html` are safe compatibility redirects to the new dashboard.

## Derived metric definitions

- **Even split:** second-half time within ±2% of first-half time.
- **Negative split:** second half more than 2% faster than first half.
- **Positive split:** second half more than 2% slower than first half.
- **Late-race slowdown:** average pace from 30–40K compared with average pace from 10–20K.
- **BQ context:** hypothetical comparison to the 2026 standards table already used in the original project; no registration buffer is applied.

## 2024 split analysis

The uploaded ZIP did not include `BM_export_splits_2024.csv`, so pacing/wall charts are intentionally hidden when 2024 is selected. Add that split CSV to `support/` and extend the preprocessing call if you want equivalent 2024 pacing analysis.
