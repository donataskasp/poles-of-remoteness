import sqlite3
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from poles.classes import NODATA
from poles.publish import tiles
from poles.publish.raster import MERC_MAX, Z9_RES

# Tiles are plain PNGs: their z/x/y path is the georeference, so rasterio's warning about the missing one is noise.
pytestmark = pytest.mark.filterwarnings("ignore::rasterio.errors.NotGeoreferencedWarning")

TILE_M = 256 * Z9_RES
# Four z9 tiles wide, two high, at tile columns 270..273 and rows 170..171 (Europe).
TX, TY = 270, 170


def _source(path: Path, seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    data = rng.integers(0, 254, size=(2 * 256, 4 * 256), dtype=np.uint8)
    data[:256, 256:512] = NODATA                      # tile (271, 170) is blank
    data[256:, :256] = 7                              # tile (270, 171) is one class
    data[256:258, :2] = 5                             # two-by-two block with three 5s and one 7 for the overview test
    data[257, 1] = 7
    transform = from_origin(-MERC_MAX + TX * TILE_M, MERC_MAX - TY * TILE_M, Z9_RES, Z9_RES)
    with rasterio.open(path, "w", driver="GTiff", width=data.shape[1], height=data.shape[0], count=1, dtype="uint8",
                       crs="EPSG:3857", transform=transform, nodata=NODATA, tiled=True, compress="deflate") as ds:
        ds.write(data, 1)
    return data


def _mbtile(mbtiles: Path, z: int, x: int, y: int) -> np.ndarray | None:
    con = sqlite3.connect(mbtiles)
    row = con.execute("SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                      (z, x, (1 << z) - 1 - y)).fetchone()
    con.close()
    if row is None:
        return None
    tmp = mbtiles.parent / f"read_{z}_{x}_{y}.png"
    tmp.write_bytes(row[0])
    with rasterio.open(tmp) as ds:
        return ds.read(1)


def test_tile_dir_cuts_z9_without_resampling(tmp_path, log):
    data = _source(tmp_path / "src.tif")
    out = tiles.tile_dir(tmp_path / "src.tif", tmp_path / "tiles", log, tmp_path / "tools.log")
    png = out / "9" / str(TX) / f"{TY}.png"
    assert png.exists()
    with rasterio.open(png) as ds:
        assert ds.count == 1 and ds.dtypes == ("uint8",)
        assert np.array_equal(ds.read(1), data[:256, :256])
    assert sorted(p.name for p in out.iterdir() if p.is_dir()) == ["9"]   # the packer builds z8 and below


def test_pack_skips_blank_and_flips_rows(tmp_path, log):
    data = _source(tmp_path / "src.tif")
    out = tiles.tile_dir(tmp_path / "src.tif", tmp_path / "tiles", log, tmp_path / "tools.log")
    stats = tiles.pack_mbtiles(out, tmp_path / "A.mbtiles", "A", tiles.lonlat_bounds(tmp_path / "src.tif"))
    assert stats["per_zoom"][9] == 7
    assert _mbtile(tmp_path / "A.mbtiles", 9, TX + 1, TY) is None
    assert np.array_equal(_mbtile(tmp_path / "A.mbtiles", 9, TX, TY + 1), data[256:, :256])
    con = sqlite3.connect(tmp_path / "A.mbtiles")
    meta = dict(con.execute("SELECT name, value FROM metadata").fetchall())
    con.close()
    assert meta["format"] == "png" and meta["minzoom"] == "0" and meta["maxzoom"] == "9" and meta["name"] == "A"
    assert len(meta["bounds"].split(",")) == 4


def test_overviews_use_mode_not_average(tmp_path, log):
    _source(tmp_path / "src.tif")
    out = tiles.tile_dir(tmp_path / "src.tif", tmp_path / "tiles", log, tmp_path / "tools.log")
    tiles.pack_mbtiles(out, tmp_path / "A.mbtiles", "A", tiles.lonlat_bounds(tmp_path / "src.tif"))
    a = _mbtile(tmp_path / "A.mbtiles", 8, TX // 2, (TY + 1) // 2)
    # z9 tile (270, 171) maps to the bottom-left quarter of z8 tile (135, 85); its first 2x2 block is 5,5,5,7 -> 5.
    assert a[128, 0] == 5
    assert a[129, 1] == 7                            # a block of plain 7s stays 7
    vals = set(np.unique(a[128:, :128]).tolist())    # that whole quarter is 5s and 7s
    assert vals == {5, 7}                            # averaging would invent a 6, cubic worse
    assert (a[:128, 128:] == NODATA).all()           # the child that was never cut stays nodata, never class 0


def test_build_chain_and_pmtiles_info(tmp_path, log):
    _source(tmp_path / "src.tif")
    meta = tiles.build(tmp_path / "src.tif", tmp_path, "A", log, tmp_path / "tools.log")
    assert (tmp_path / "A.pmtiles").exists() and meta["bytes"] == (tmp_path / "A.pmtiles").stat().st_size
    assert meta["max_zoom"] == 9 and meta["min_zoom"] == 0 and meta["tile_type"] == "png"
    assert meta["tiles"] == sum(meta["per_zoom"].values())
    for m in ("tiles_A.ok", "A.mbtiles.ok", "A.pmtiles.ok"):
        assert (tmp_path / m).exists()
    again = tiles.build(tmp_path / "src.tif", tmp_path, "A", log, tmp_path / "tools.log")
    assert again == meta


def test_pmtiles_info_parses_show_output():
    text = ("pmtiles spec version: 3\ntile type: png\nbounds: 9.8,50.1,12.3,52.2\nmin zoom: 0\nmax zoom: 9\n"
            "center: 11,51,5\naddressed tiles count: 42\ntile entries count: 42\ntile contents count: 40\n")
    assert tiles.parse_show(text) == {"tiles": 42, "min_zoom": 0, "max_zoom": 9, "tile_type": "png"}


# ---------- beyond the plan's five: the cases a whole-region run hits ----------

def _write(path: Path, data: np.ndarray, tx: int, ty: int) -> None:
    transform = from_origin(-MERC_MAX + tx * TILE_M, MERC_MAX - ty * TILE_M, Z9_RES, Z9_RES)
    with rasterio.open(path, "w", driver="GTiff", width=data.shape[1], height=data.shape[0], count=1, dtype="uint8",
                       crs="EPSG:3857", transform=transform, nodata=NODATA, tiled=True, compress="deflate") as ds:
        ds.write(data, 1)


def test_packed_tiles_are_single_band_with_nodata_where_the_raster_had_none(tmp_path, log):
    """The tiler flags what the raster does not cover with an alpha band, never with a class value: with
    --no-alpha it fills that space with 0, which is the class "within 50 m of a road", and the sea would
    publish as roadside. The packer folds alpha back into NODATA and writes single band grey tiles."""
    data = np.random.default_rng(3).integers(0, 254, size=(256, 256), dtype=np.uint8)
    data[100:150, 60:120] = NODATA                   # an interior hole, inside one tile
    _write(tmp_path / "src.tif", data, TX, TY)
    out = tiles.tile_dir(tmp_path / "src.tif", tmp_path / "tiles", log, tmp_path / "tools.log")
    with rasterio.open(out / "9" / str(TX) / f"{TY}.png") as ds:
        assert ds.count == 2                          # on disk the hole is alpha, not a class
    tiles.pack_mbtiles(out, tmp_path / "A.mbtiles", "A", tiles.lonlat_bounds(tmp_path / "src.tif"))
    packed = _mbtile(tmp_path / "A.mbtiles", 9, TX, TY)
    assert np.array_equal(packed, data)               # holes read back as NODATA, everything else unchanged
    with rasterio.open(tmp_path / f"read_9_{TX}_{TY}.png") as ds:
        assert ds.count == 1 and ds.dtypes == ("uint8",)


def test_one_tile_raster_builds_a_pyramid_that_stops_where_the_data_vanishes(tmp_path, log):
    """One z9 tile is half a pixel of the z0 world tile, and mode drops it: the archive starts at z1, and
    every zoom the archive claims has tiles in it."""
    data = np.full((256, 256), 12, dtype=np.uint8)
    _write(tmp_path / "src.tif", data, TX, TY)
    meta = tiles.build(tmp_path / "src.tif", tmp_path, "B", log, tmp_path / "tools.log")
    assert meta["per_zoom"] == {z: 1 for z in range(1, 10)}
    assert meta["tiles"] == 9 and meta["min_zoom"] == 1 and meta["max_zoom"] == 9
    assert np.array_equal(_mbtile(tmp_path / "B.mbtiles", 9, TX, TY), data)


def test_a_raster_that_is_all_nodata_fails_loudly(tmp_path, log):
    _write(tmp_path / "src.tif", np.full((256, 512), NODATA, dtype=np.uint8), TX, TY)
    out = tiles.tile_dir(tmp_path / "src.tif", tmp_path / "tiles", log, tmp_path / "tools.log")
    with pytest.raises(RuntimeError, match="no non-blank tiles"):
        tiles.pack_mbtiles(out, tmp_path / "A.mbtiles", "A", tiles.lonlat_bounds(tmp_path / "src.tif"))


def test_tiles_on_the_antimeridian_column(tmp_path, log):
    """The world's last tile column: nothing wraps past x = 511 and the eastern bound is 180 degrees."""
    data = np.full((256, 512), 30, dtype=np.uint8)
    _write(tmp_path / "src.tif", data, 510, TY)
    assert abs(tiles.lonlat_bounds(tmp_path / "src.tif")[2] - 180.0) < 1e-9
    out = tiles.tile_dir(tmp_path / "src.tif", tmp_path / "tiles", log, tmp_path / "tools.log")
    assert sorted(p.name for p in (out / "9").iterdir()) == ["510", "511"]
    stats = tiles.pack_mbtiles(out, tmp_path / "A.mbtiles", "A", tiles.lonlat_bounds(tmp_path / "src.tif"))
    assert stats["per_zoom"][9] == 2
    assert np.array_equal(_mbtile(tmp_path / "A.mbtiles", 9, 511, TY), data[:, 256:])


def test_a_half_cut_tile_directory_resumes(tmp_path, log):
    """A run killed mid-cut leaves a directory without its marker: the next build fills the gaps."""
    _source(tmp_path / "src.tif")
    out = tiles.tile_dir(tmp_path / "src.tif", tmp_path / "tiles", log, tmp_path / "tools.log")
    keep = (out / "9" / str(TX) / f"{TY}.png").read_bytes()
    for png in (out / "9" / str(TX + 2)).rglob("*.png"):
        png.unlink()
    tiles.tile_dir(tmp_path / "src.tif", out, log, tmp_path / "tools.log")
    assert (out / "9" / str(TX) / f"{TY}.png").read_bytes() == keep
    assert (out / "9" / str(TX + 2) / f"{TY}.png").exists()


def test_build_recuts_when_the_marker_is_missing(tmp_path, log):
    _source(tmp_path / "src.tif")
    meta = tiles.build(tmp_path / "src.tif", tmp_path, "A", log, tmp_path / "tools.log")
    for name in ("tiles_A.ok", "A.mbtiles.ok", "A.pmtiles.ok"):
        (tmp_path / name).unlink()
    (tmp_path / "A.pmtiles").unlink()                 # as a crash between convert and mark would leave it
    assert tiles.build(tmp_path / "src.tif", tmp_path, "A", log, tmp_path / "tools.log") == meta


def test_parse_show_reads_the_real_pmtiles_output():
    """Captured from `pmtiles show` on a test archive (pmtiles 1.31, 2026-08-22); the parser ignores the rest."""
    text = ("pmtiles spec version: 3\ntile type: png\n"
            "bounds: (long: 9.843750, lat: 50.736455) (long: 12.656250, lat: 51.618017)\n"
            "min zoom: 0\nmax zoom: 9\ncenter: (long: 11.250000, lat: 51.177236)\ncenter zoom: 0\n"
            "addressed tiles count: 42\ntile entries count: 42\ntile contents count: 40\nclustered: true\n"
            "internal compression: gzip\ntile compression: none\ntype overlay\nversion 1\n"
            "description A: distance class index per pixel, 254 edge, 255 nodata\nformat png\nmaxzoom 9\n"
            "minzoom 0\nname A\n")
    assert tiles.parse_show(text) == {"tiles": 42, "min_zoom": 0, "max_zoom": 9, "tile_type": "png"}


def test_parse_show_refuses_output_it_does_not_recognise():
    with pytest.raises(ValueError, match="max zoom"):
        tiles.parse_show("tile type: png\nmin zoom: 0\naddressed tiles count: 3\n")


def test_overviews_never_invent_a_class_at_a_nodata_boundary(tmp_path, log):
    """GDAL's own overviews take the mode of the class band with 0 sitting under the transparent pixels, and
    that 0 votes: a coastal block of {class, other class, nothing, nothing} comes out as class 0, "within 50 m
    of a road", at alpha 255, so the fold never sees it. The packer builds the overviews itself: nodata votes
    as itself, a data class wins a tie against it, and the lowest class index wins a tie between data classes."""
    r, c = np.meshgrid(np.arange(256), np.arange(256), indexing="ij")
    data = np.where((r + c) % 2 == 0, 100, 150).astype(np.uint8)
    data[:, 129:] = NODATA                    # a coast one column past the block edge: every block on it is 2 land, 2 sea
    _write(tmp_path / "src.tif", data, TX, TY)
    meta = tiles.build(tmp_path / "src.tif", tmp_path, "C", log, tmp_path / "tools.log")
    con = sqlite3.connect(tmp_path / "C.mbtiles")
    rows = con.execute("SELECT zoom_level, tile_column, tile_row FROM tiles").fetchall()
    con.close()
    seen: set[int] = set()
    for z, x, row in rows:
        seen |= set(np.unique(_mbtile(tmp_path / "C.mbtiles", z, x, (1 << z) - 1 - row)).tolist())
    assert seen == {100, 150, NODATA}         # a stray 0 would be the sea published as roadside
    assert np.array_equal(_mbtile(tmp_path / "C.mbtiles", 9, TX, TY), data)   # nodata exactly where the source had none
    expect = np.full((256, 256), NODATA, np.uint8)
    expect[:128, :64] = 100                   # 100 and 150 tie in every land block, the lower class index wins
    assert np.array_equal(_mbtile(tmp_path / "C.mbtiles", 8, TX // 2, TY // 2), expect)
    assert meta["min_zoom"] == 1              # the last land pixel is outvoted three to one in the z0 block


def test_a_truncated_tile_is_rejected(tmp_path, log):
    """--resume regenerates only missing files, so a run killed mid-tile leaves a half written PNG behind."""
    _source(tmp_path / "src.tif")
    out = tiles.tile_dir(tmp_path / "src.tif", tmp_path / "tiles", log, tmp_path / "tools.log")
    png = out / "9" / str(TX) / f"{TY + 1}.png"
    png.write_bytes(png.read_bytes()[: png.stat().st_size // 2])
    with pytest.raises(RuntimeError, match=f"{TY + 1}[.]png"):
        tiles.pack_mbtiles(out, tmp_path / "A.mbtiles", "A", tiles.lonlat_bounds(tmp_path / "src.tif"))


def test_a_tile_that_is_not_grey_is_rejected(tmp_path, log):
    _source(tmp_path / "src.tif")
    out = tiles.tile_dir(tmp_path / "src.tif", tmp_path / "tiles", log, tmp_path / "tools.log")
    with MemoryFile(filename="rgb.png") as mem:
        with mem.open(driver="PNG", width=256, height=256, count=3, dtype="uint8") as ds:
            ds.write(np.zeros((3, 256, 256), np.uint8))
        (out / "9" / str(TX) / f"{TY}.png").write_bytes(mem.read())
    with pytest.raises(RuntimeError, match="bands"):
        tiles.pack_mbtiles(out, tmp_path / "A.mbtiles", "A", tiles.lonlat_bounds(tmp_path / "src.tif"))


def test_pack_names_a_tile_directory_that_is_not_there(tmp_path):
    with pytest.raises(RuntimeError, match="no tile directory"):
        tiles.pack_mbtiles(tmp_path / "gone", tmp_path / "A.mbtiles", "A", (0.0, 0.0, 1.0, 1.0))
