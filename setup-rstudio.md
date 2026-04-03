# Running lonboard Py Shiny in RStudio Server via uv

Step-by-step for getting this running in an RStudio Server session.

WIP - not verified yet, it's always the hosting I struggle with ...


## 1. Install uv

In the RStudio **Terminal** tab (not the R console):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

This drops the binary into `~/.local/bin/uv`. If that's not on your PATH
already, add it:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Verify:

```bash
uv --version
```

## 2. Create a venv with a recent Python

uv can fetch and install Python itself — no system packages needed:

```bash
# Install Python 3.12 (or whatever's latest stable)
uv python install 3.14

# Create a venv using it
uv venv --python 3.14 ~/.venvs/lonboard-cog

# Activate
source ~/.venvs/lonboard-cog/bin/activate
```

Check it's the right one:

```bash
which python
# should be ~/.venvs/lonboard-cog/bin/python
python --version
# Python 3.14.x
```

## 3. Install dependencies

Still in the activated venv in the Terminal:

```bash
uv pip install \
  shiny \
  shinywidgets \
  lonboard \
  async-geotiff \
  obstore \
  pillow \
  numpy \
  matplotlib
```

This should be fast — uv's resolver is much quicker than pip. The
async-geotiff and obstore wheels include pre-compiled Rust binaries so
no compilation needed.

**Potential gotcha:** If you're on an older Linux (e.g. CentOS 7 / RHEL 7
based RStudio Server), the manylinux wheels for async-geotiff might not
work. You'd need at least manylinux2014 (glibc 2.17). Most modern
RStudio Server installs on Ubuntu 20.04+ or 22.04+ will be fine.

## 4. Register this Python with reticulate

Back in the **R console**:

```r
# Tell reticulate to use our venv
library(reticulate)
use_virtualenv("~/.venvs/lonboard-cog", required = TRUE)

# Verify
py_config()
# Should show the path to ~/.venvs/lonboard-cog/bin/python

# Quick smoke test
py_run_string("import lonboard; print(lonboard.__version__)")
```

You can also make this sticky for the project by putting it in `.Rprofile`:

```r
Sys.setenv(RETICULATE_PYTHON = "~/.venvs/lonboard-cog/bin/python")
```

Or using a `reticulate` config file (`.Renviron`):

```
RETICULATE_PYTHON=~/.venvs/lonboard-cog/bin/python
```

## 5. Get the app

Save `app.py` somewhere in your project directory. Or clone/copy it:

```bash
# In Terminal, with the venv still activated
mkdir -p ~/lonboard-cog-demo
cd ~/lonboard-cog-demo
# copy app.py here
```

## 6. Run the Shiny app

### Option A: From the Terminal (simplest)

```bash
cd ~/lonboard-cog-demo
source ~/.venvs/lonboard-cog/bin/activate
shiny run app.py --port 8765
```

Then open `http://localhost:8765` (or `http://your-server:8765` if remote).

If you're behind an RStudio Server proxy, you may need to use the
RStudio Server's port forwarding. On Pawsey/NCI HPC you'd typically
SSH tunnel:

```bash
# On your local machine:
ssh -L 8765:localhost:8765 user@rstudio-server-host
```

### Option B: From R via reticulate

```r
library(reticulate)
use_virtualenv("~/.venvs/lonboard-cog", required = TRUE)

# Source and run
shiny <- import("shiny")
# This won't work directly because shiny.run() blocks —
# better to use the terminal approach above
```

Honestly, Option A (Terminal tab) is the clean way. Py Shiny's `shiny run`
starts its own uvicorn server and that's the intended entry point.

### Option C: Background job in RStudio

In RStudio, go to **Tools → Background Jobs → Start Background Job**,
point it at a shell script:

```bash
#!/bin/bash
source ~/.venvs/lonboard-cog/bin/activate
cd ~/lonboard-cog-demo
shiny run app.py --port 8765
```

This keeps it running while you work in R in the main console.

## 7. What to expect

When you open the app:

- **GEBCO dataset**: The first pan/zoom will be slow-ish as it fetches the
  COG header from Pawsey. After that, tiles stream in on demand. The
  `render_tile` callback applies your chosen colormap and depth range.
  The GEBCO 2024 COG is ~7.5 GB on disk but you're only ever fetching
  the tiles visible in your viewport at the current zoom level.

- **NZ RGB dataset**: Should be fast — tiles are small, 3-band uint8,
  direct pass-through to PNG. Same COG Kyle used in the blog post.

- **Changing colormap/depth range**: Currently recreates the whole map
  widget (naive approach). In production you'd use Shiny's reactive
  efficient update pattern to only swap the render callback.

## Troubleshooting

**"ModuleNotFoundError: No module named 'lonboard'"**
→ You're not in the right venv. Make sure to `source activate` first, or
check that `which python` points to the venv.

**Tiles not loading / timeout errors**
→ Check that your server can reach `projects.pawsey.org.au` and
`nz-imagery.s3.ap-southeast-2.amazonaws.com`. Some HPC firewalls block
outbound HTTPS to non-whitelisted domains.

**"Address already in use"**
→ Change the port: `shiny run app.py --port 8766`

**Widget doesn't render / blank map**
→ The lonboard widget needs the Jupyter widget JS to be served. Py Shiny's
shinywidgets should handle this, but if you see a blank space, try
`uv pip install ipywidgets` explicitly.

## What this proves for R

Once you have this running, the argument writes itself:

1. The `render_tile` callback is doing exactly what your plumber2 tile
   endpoint does — read COG tile, apply colormap, return PNG.

2. The `async-geotiff` Rust core is the same `async-tiff` crate that
   `rustycogs` wraps for R.

3. The missing piece for R-native is a deck.gl-raster htmlwidget.
   Everything else (I/O, rendering, storage access) already exists
   in the hypertidy ecosystem.

4. Py Shiny running inside RStudio Server is a viable bridge *today*
   while that htmlwidget gets built.
