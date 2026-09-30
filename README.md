# allonboard

A working demo of [lonboard](https://developmentseed.org/lonboard/)'s new
Cloud-Optimized GeoTIFF support, deployed as a
[Shiny for Python](https://shiny.posit.co/py/) app — and a survey of what
it would take to do the same thing natively in R.

![GEBCO 2024 bathymetry rendered via lonboard](screenshot.png)

## What this is

On 2 April 2026, Kyle Barron announced COG rendering in lonboard via a
`render_tile` callback
([blog post](https://developmentseed.org/lonboard/latest/blog/2026/04/02/cloud-optimized-geotiffs-in-lonboard/)).
The key feature: you write a Python function that receives raw tile data
from a Cloud-Optimized GeoTIFF and returns a PNG. You control the
colormaps, band math, masking, hillshade — whatever you want. Tiles are
fetched asynchronously via
[async-tiff](https://github.com/developmentseed/async-tiff) (Rust) and
[deck.gl-raster](https://developmentseed.org/deck.gl-raster/) handles
browser-side reprojection.

This repo contains:

| File | What it is |
|---|---|
| `app.py` | Py Shiny app with two COG datasets and interactive render controls |
| `setup-guide.md` | How to run the app on any Linux box |
| `nectar-setup-guide.md` | Specific notes for deploying on NeCTAR OpenStack (Australian research cloud) |

## The demo

Two datasets with full `render_tile` control:

**GEBCO 2024 bathymetry** — a ~7.5 GB single-band Int16 global elevation
COG hosted on [Pawsey](https://pawsey.org.au/) (also mirrored on
[Source Cooperative](https://source.coop/alexgleith/gebco-2024)). The
render callback applies matplotlib colormaps, adjustable depth range, and
optional hillshade. This is the interesting case: raw elevation values
transformed to colour on the fly per tile.

**NZ Imagery RGB** — a 3-band uint8 COG from the
[NZ Imagery AWS Open Data](https://registry.opendata.aws/nz-imagery/)
bucket (same file Kyle used in the lonboard blog post). Straightforward
band pass-through to PNG.

## Why this matters for R

The architecture of lonboard's COG rendering is:

```
async-tiff (Rust) → Python bindings → render_tile callback → PNG
  ↕ Jupyter widget comms                                       ↕
deck.gl-raster (browser) ← reprojection + tile selection  ← tiles
```

R already has packages covering most of this pipeline. What's missing is
the last mile: a browser widget that does client-side reprojection and
talks back to R for tile data.

### What exists in R today

The render callback — reading a COG tile and turning it into a styled
PNG — is well covered:

| What | Python (lonboard stack) | R packages |
|---|---|---|
| COG I/O (HTTP range requests) | async-geotiff / async-tiff | gdalraster (vsicurl), vapour, terra, stars |
| Async COG I/O (Rust) | async-tiff crate | [rustycogs](https://github.com/hypertidy/rustycogs) (same crate, extendr bindings) |
| Object storage access | obstore | gdalraster (vsicurl, vsis3), terra |
| Band math / array ops | numpy | base R, terra, stars |
| Colormaps for ocean/ice/SST | matplotlib | [palr](https://github.com/AustralianAntarcticDivision/palr), scales, viridisLite |
| Tile grid calculation | morecantile | [grout](https://github.com/hypertidy/grout) |
| Serve tiles over HTTP | (not needed — Jupyter comms) | [plumber2](https://github.com/posit-dev/plumber2), httpuv |
| Interactive map display | lonboard (deck.gl + anywidget) | leaflet, leafem, [rdeck](https://github.com/anthonynorth/rdeck), mapgl |
| Client-side COG reprojection | deck.gl-raster | **← the gap** |

The pattern of "read COG tile → apply colormap → serve PNG" works today
in R with gdalraster + plumber2 (or terra + plumber2). An R plumber2 tile
endpoint is architecturally the same as lonboard's `render_tile`, just
served over HTTP rather than Jupyter widget comms.

### The gap

What R doesn't have is a browser-side component equivalent to
[deck.gl-raster](https://developmentseed.org/deck.gl-raster/) — the
piece that handles tile selection based on viewport, client-side
reprojection from the source CRS to Web Mercator, and efficient
communication back to R for more tiles.

leaflet can display tiles from a URL template (and leafem can overlay
local rasters), but neither does on-the-fly reprojection from arbitrary
source CRS. rdeck wraps deck.gl but doesn't yet include the raster tile
layer from deck.gl-raster.

A deck.gl-raster htmlwidget (or an extension to rdeck) that can request
tiles from an R backend would close this gap. The server-side rendering
pipeline already exists.

### Packages worth watching

Some R packages that are relevant to building this out or that solve
related problems:

- [gdalraster](https://github.com/USDAForestService/gdalraster) — fast
  GDAL bindings for R, COG access via vsicurl, the most likely engine
  for an R `render_tile` equivalent
- [terra](https://rspatial.github.io/terra/) — raster/vector analysis,
  reads COGs, has its own `plot` and `plet` (leaflet) methods
- [stars](https://r-spatial.github.io/stars/) — spatiotemporal arrays,
  lazy reading, proxy objects for large rasters
- [vapour](https://github.com/hypertidy/vapour) — lightweight GDAL API
  for R, fast window reads from COGs
- [rdeck](https://github.com/anthonynorth/rdeck) — deck.gl htmlwidget
  for R, the most natural place to add a raster tile layer
- [leafem](https://github.com/r-spatial/leafem) — adds COG/raster
  overlay to leaflet (via georaster-layer-for-leaflet), no reprojection
- [mapgl](https://github.com/walkerke/mapgl) — MapLibre GL JS bindings
  for R
- [tiler](https://github.com/ropensci/tiler) — generates map tile sets
  from rasters (pre-computed, not on-the-fly)
- [rustycogs](https://github.com/hypertidy/rustycogs) — extendr
  bindings to the same async-tiff Rust crate that lonboard uses
- [palr](https://github.com/AustralianAntarcticDivision/palr) — colour
  palettes for ocean, ice, and SST data

## Running the demo

See [setup-guide.md](setup-guide.md) for the general setup instructions.
See [nectar-setup-guide.md](nectar-setup-guide.md) for NeCTAR-specific
deployment notes.

Quick start:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install lonboard shiny shinywidgets async-geotiff obstore \
  pillow numpy matplotlib uvicorn
shiny run app.py
```

## COG data sources

| Dataset | URL | Size | Notes |
|---|---|---|---|
| GEBCO 2024 | `https://projects.pawsey.org.au/idea-gebco-tif/GEBCO_2024.tif` | ~4 GB | Single-band Int16 elevation, EPSG:4326 |
| GEBCO 2024 (mirror) | `https://data.source.coop/alexgleith/gebco-2024/GEBCO_2024.tif` | ~4 GB | Same source netcdf file, different cog-conversion |
| NZ Imagery | `s3://nz-imagery/new-zealand/new-zealand_2024-2025_10m/rgb/2193/CC11.tiff` | ~250 MB | 3-band RGB uint8, NZGD2000 / NZTM (EPSG:2193) |

## Links

- [lonboard COG blog post](https://developmentseed.org/lonboard/latest/blog/2026/04/02/cloud-optimized-geotiffs-in-lonboard/) — Kyle Barron's announcement
- [async-tiff](https://github.com/developmentseed/async-tiff) — the Rust COG reader underneath
- [deck.gl-raster](https://developmentseed.org/deck.gl-raster/) — browser-side raster tile rendering
- [Shiny for Python](https://shiny.posit.co/py/) — the app framework (Posit)
- [GEBCO](https://www.gebco.net/) — General Bathymetric Chart of the Oceans
