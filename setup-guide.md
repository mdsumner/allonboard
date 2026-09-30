# Setup guide

How to run the lonboard COG demo app on any Linux box (or macOS). This
covers local development and quick deployment. For NeCTAR-specific
hosting with nginx and HTTPS, see
[nectar-setup-guide.md](nectar-setup-guide.md).

## Requirements

- A Linux or macOS machine (Windows via WSL2 should also work)
- Internet access (the app fetches COG tiles from remote storage)
- ~100 MB disk for the Python venv

## 1. Install uv

[uv](https://docs.astral.sh/uv/) manages Python versions and packages.
Single binary, no root needed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Add to PATH if needed:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

## 2. Create a Python environment

uv can fetch Python itself — no system Python required:

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
```

We use Python 3.12 because lonboard's native Rust dependencies (async-tiff,
obstore) have good wheel coverage for it. Python 3.14 is too new for
reliable compatibility with the current scientific Python stack.

## 3. Install dependencies

```bash
uv pip install \
  lonboard \
  shiny \
  shinywidgets \
  async-geotiff \
  obstore \
  pillow \
  numpy \
  matplotlib \
  uvicorn
```

This is fast — uv's resolver is much quicker than pip, and the Rust-based
packages (async-geotiff, obstore) ship pre-compiled wheels.

## 4. Run the app

```bash
shiny run app.py
```

Opens on `http://localhost:8765` by default. To specify a port:

```bash
shiny run app.py --port 8080
```

To bind to all interfaces (e.g. on a remote server):

```bash
shiny run app.py --host 0.0.0.0 --port 8765
```

## What to expect

**GEBCO bathymetry**: The first load fetches the COG header from Pawsey
(~16 KB). Then tiles stream in on demand as you pan/zoom. The render
callback applies your chosen colormap and depth range per tile. The
source file is ~7.5 GB but you only ever fetch the tiles visible at the
current zoom level.

**NZ RGB imagery**: Fast — small tiles, 3-band uint8, direct
pass-through to PNG.

**Sidebar controls**: Changing the colormap or depth range currently
recreates the map widget. In production you'd use Shiny's efficient
reactive update pattern to swap only the render callback.

## Troubleshooting

**"ModuleNotFoundError: No module named 'lonboard'"**
→ Make sure the venv is activated: `source .venv/bin/activate`

**Tiles not loading / timeout errors**
→ Check that you can reach `projects.pawsey.org.au` and
`nz-imagery.s3.ap-southeast-2.amazonaws.com`. Some institutional
firewalls block outbound HTTPS.

**"Address already in use"**
→ Change the port: `shiny run app.py --port 8766`

**Widget renders but map is blank**
→ Try `uv pip install ipywidgets` explicitly. The lonboard widget
needs Jupyter widget JS infrastructure, which shinywidgets normally
provides.

**"RasterLayer has no attribute 'from_geotiff'"**
→ You're on lonboard < 0.16.0. The `from_geotiff` API was added in the
0.16.0 release (2 April 2026). Run `uv pip install --upgrade lonboard`.

## Running on a remote server

If you're on a remote machine (HPC, cloud VM, etc.), the simplest
approach is an SSH tunnel:

```bash
# On your local machine:
ssh -L 8765:localhost:8765 user@remote-host
```

Then open `http://localhost:8765` in your local browser.

For production hosting with nginx, HTTPS, and systemd, see
[nectar-setup-guide.md](nectar-setup-guide.md) — the pattern
generalises to any Ubuntu server.
