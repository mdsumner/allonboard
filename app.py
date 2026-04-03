"""
Lonboard COG Explorer — Py Shiny demo
======================================
Two COG datasets with full render_tile control:
  1. GEBCO 2024 bathymetry (Pawsey-hosted COG, single-band Int16 elevation)
  2. NZ Imagery RGB (AWS Open Data, 3-band uint8)

Run with:
  shiny run app.py

Requires:
  uv pip install shiny shinywidgets lonboard async-geotiff obstore pillow numpy matplotlib
"""

import io
import numpy as np
from shiny import reactive, req
from shiny.express import input, ui
from shinywidgets import render_widget

# ---------------------------------------------------------------------------
# lonboard + async-geotiff imports
# ---------------------------------------------------------------------------
from async_geotiff import GeoTIFF, Tile
from async_geotiff.utils import reshape_as_image
from obstore.store import S3Store, HTTPStore
from PIL import Image

from lonboard import Map, RasterLayer
from lonboard.raster import EncodedImage

# ---------------------------------------------------------------------------
# Colormaps for bathymetry — using matplotlib for now,
# but in R you'd use palr::bathyDeepPal() or a custom palette
# ---------------------------------------------------------------------------
import matplotlib
import matplotlib.cm as cm

# Build a blue-to-white bathymetry colormap (ocean only)
# This is the creative bit — full Python control over rendering
_bathy_cmap = cm.get_cmap("ocean")  # deep blue -> cyan -> white
_bathy_norm = matplotlib.colors.Normalize(vmin=-11000, vmax=0)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
ui.page_opts(title="Lonboard COG Explorer", fillable=True)

with ui.sidebar():
    ui.h3("COG Dataset")
    ui.input_select(
        "dataset",
        "Choose dataset:",
        choices={
            "gebco": "GEBCO Bathymetry (single-band, Int16)",
            "nz_rgb": "NZ Imagery (RGB, uint8)",
        },
    )

    ui.hr()
    ui.h4("Bathymetry options")
    ui.p("(Only apply to GEBCO dataset)")

    ui.input_select(
        "colormap",
        "Colormap:",
        choices={
            "ocean": "Ocean (blue → white)",
            "terrain": "Terrain (land + sea)",
            "viridis": "Viridis",
            "cividis": "Cividis",
            "RdYlBu_r": "Red-Yellow-Blue (reversed)",
        },
    )

    ui.input_slider(
        "depth_range",
        "Depth range (m):",
        min=-11000,
        max=8500,
        value=(-8000, 0),
        step=100,
    )

    ui.input_checkbox("hillshade", "Apply simple hillshade", value=False)

    ui.hr()
    ui.markdown(
        """
        **What this demonstrates:**

        The `render_tile` callback gives you *full Python control*
        over how each COG tile is rendered — band math, colormaps,
        masking, hillshade, ML inference, whatever you want.

        This is architecturally identical to an R plumber2 tile API
        backed by `gdalraster`, but the tiles are served via Jupyter
        comms rather than HTTP. The `async-geotiff` Rust core is the
        same `async-tiff` crate used by `rustycogs` in R.
        """
    )


# ---------------------------------------------------------------------------
# GeoTIFF handles (created once, reused across renders)
# ---------------------------------------------------------------------------
# GEBCO 2024 COG on Pawsey (Michael's copy)
# Also available at: https://data.source.coop/alexgleith/gebco-2024/GEBCO_2024.tif
GEBCO_BASE_URL = "https://projects.pawsey.org.au"
GEBCO_COG_PATH = "idea-gebco-tif/GEBCO_2024.tif"

# NZ Imagery — same bucket/path Kyle used in the lonboard blog post
NZ_BUCKET = "nz-imagery"
NZ_COG_PATH = "new-zealand/new-zealand_2024-2025_10m/rgb/2193/CC11.tiff"


@reactive.calc
async def geotiff_gebco():
    """Open GEBCO 2024 COG via HTTP from Pawsey."""
    store = HTTPStore(GEBCO_BASE_URL)
    return await GeoTIFF.open(GEBCO_COG_PATH, store=store)


@reactive.calc
async def geotiff_nz():
    """Open NZ imagery COG from S3."""
    store = S3Store(NZ_BUCKET, region="ap-southeast-2", skip_signature=True)
    return await GeoTIFF.open(NZ_COG_PATH, store=store)


# ---------------------------------------------------------------------------
# render_tile callbacks — this is where the magic happens
# ---------------------------------------------------------------------------
def make_gebco_renderer(cmap_name: str, vmin: float, vmax: float, hillshade: bool):
    """Factory for GEBCO render_tile with current UI settings.

    In R, the equivalent would be something like:
        render_tile <- function(tile_array) {
            pal <- palr::bathyDeepPal(palette = TRUE)
            vals <- scales::rescale(tile_array, from = c(vmin, vmax))
            cols <- pal(vals)
            png::writePNG(cols)
        }
    """
    cmap = cm.get_cmap(cmap_name)
    norm = matplotlib.colors.Normalize(vmin=vmin, vmax=vmax)

    def render_tile(tile: Tile) -> EncodedImage:
        # tile.array.data shape: (1, height, width) for single-band
        arr = tile.array.data[0].astype(np.float32)

        if hillshade:
            # Simple hillshade: gradient magnitude as shading factor
            dy, dx = np.gradient(arr)
            slope = np.sqrt(dx**2 + dy**2)
            shade = 1.0 - np.clip(slope / 500.0, 0, 0.6)
        else:
            shade = 1.0

        # Apply colormap
        rgba = cmap(norm(arr))  # (H, W, 4) float [0,1]
        rgba[:, :, :3] *= shade if isinstance(shade, float) else shade[:, :, np.newaxis]

        # Convert to uint8 PNG
        img_array = (rgba * 255).astype(np.uint8)
        img = Image.fromarray(img_array, mode="RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return EncodedImage(data=buf.getvalue(), media_type="image/png")

    return render_tile


def render_tile_nz_rgb(tile: Tile) -> EncodedImage:
    """Render NZ RGB imagery — straightforward band pass-through.

    In R with gdalraster, this would just be:
        ds <- new(GDALRaster, cog_path, TRUE)
        arr <- ds$read(...)
        png::writePNG(arr / 255)
    """
    image_array = reshape_as_image(tile.array.data)  # (H, W, 3)
    img = Image.fromarray(image_array)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return EncodedImage(data=buf.getvalue(), media_type="image/png")


# ---------------------------------------------------------------------------
# Map widget
# ---------------------------------------------------------------------------
@render_widget
async def map():
    dataset = input.dataset()

    if dataset == "gebco":
        geotiff = await geotiff_gebco()
        renderer = make_gebco_renderer(
            cmap_name=input.colormap(),
            vmin=input.depth_range()[0],
            vmax=input.depth_range()[1],
            hillshade=input.hillshade(),
        )
        layer = RasterLayer.from_geotiff(geotiff, render_tile=renderer)
        return Map(layer, _initial_view_state={"longitude": 150, "latitude": -60, "zoom": 3})

    else:
        geotiff = await geotiff_nz()
        layer = RasterLayer.from_geotiff(geotiff, render_tile=render_tile_nz_rgb)
        return Map(layer, _initial_view_state={"longitude": 172.5, "latitude": -43.5, "zoom": 8})
