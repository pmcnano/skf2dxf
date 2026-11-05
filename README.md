# skf2dxf

Converts AutoSketch 10 drawings (`.skf`) to DXF so they open in AutoCAD, without AutoSketch.
The format is undocumented; the parser was reverse-engineered from sample files and checked
against AutoSketch's own DWG export. Try it at https://skf2dxf.com.

## Command line

    uv run skf2dxf drawing.skf drawing.dxf

## Web page

The page runs the same converter in the browser with Pyodide, so files never leave the computer
unless someone chooses to send one. It previews drawings (layers, PDF export), downloads
everything as a ZIP, and works offline once loaded.

    bin/serve        # page + report API on http://localhost:8000/ (PORT=3000 bin/serve)
    npm run deploy   # Cloudflare Workers: static assets plus src/index.js for /api/report

`bin/build` bundles `web/` with `skf2dxf.py` and `preview.py` into `dist/`.

## Drawings people send

The "send us this file" form stores the drawing and the converter's report in Workers KV and
emails an alert to the `REPORT_EMAIL` secret, which must be an address verified in Email
Routing (`npx wrangler secret put REPORT_EMAIL`; locally, `.dev.vars`). Senders are limited to 5
files a minute.

    uv run python tools/pull_reports.py [--delete]   # into samples/reports/
    uv run python tools/survey.py samples/reports

## Usage counts

The page posts anonymous events to `/api/event`, stored in the `skf2dxf_events` Analytics
Engine dataset: blob1 event, blob2 result, blob3 AutoSketch version, blob4 warnings, blob5
language, blob6 country; double1 size in KB, double2 items converted. Query them with an API
token that has Account Analytics Read:

    curl https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/analytics_engine/sql \
      -H "Authorization: Bearer $TOKEN" -d "
        SELECT blob2 AS result, blob3 AS version, SUM(_sample_interval) AS files
        FROM skf2dxf_events WHERE blob1 = 'convert' AND timestamp > NOW() - INTERVAL '30' DAY
        GROUP BY result, version ORDER BY files DESC"

## Tests

Tests run against private sample drawings in `samples/` (gitignored), listed by role in
`samples/samples.json`, and skip when they're absent.

    uv run pytest
    npm test        # the Worker (src/index.js), with fake bindings

## Checking a batch of drawings

    uv run python tools/survey.py path/to/folder

Lists each drawing that crashed, skipped something, or has records the parser misread. Those
are the ones worth exporting from AutoSketch as DWG to compare against.

## License

MIT, see `LICENSE`. `web/fonts/DejaVuSans.ttf` keeps its own license (`LICENSE_DEJAVU.txt`).
`patterns.json` holds the hatch patterns AutoSketch stores in drawings, collected so drawings
that use one without storing it still get their fill.
