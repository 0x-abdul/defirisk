from __future__ import annotations

import binascii
import struct
import zlib
from pathlib import Path

import pytest

import importlib.util

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("png_public_boundary", ROOT / "scripts/ci/candidate_boundary.py")
assert SPEC and SPEC.loader
boundary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boundary)


SIGNATURE = b"\x89PNG\r\n\x1a\n"
PRIVATE = b"C:\\Users\\operator\\private-assessment.json"


def chunk(kind: bytes, content: bytes) -> bytes:
    return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", binascii.crc32(kind + content) & 0xffffffff)


def header(width: int = 1, height: int = 1, *, color: int = 0, interlace: int = 0) -> bytes:
    return chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, interlace))


def png(*metadata: bytes, pixels: bytes = b"\x00", interlace: int = 0) -> bytes:
    return SIGNATURE + header(len(pixels), interlace=interlace) + b"".join(metadata) + chunk(b"IDAT", zlib.compress(b"\x00" + pixels, level=0)) + chunk(b"IEND", b"")


def scan(raw: bytes, tmp_path: Path, suffix: str = ".png") -> list:
    if hasattr(boundary, "_scan_artifact"):
        failures = []
        boundary._scan_artifact(raw, "public-image" + suffix, failures)
        return failures
    path = tmp_path / ("public-image" + suffix)
    path.write_bytes(raw)
    return boundary._scan_text_file(path, "site/dist/public-image" + suffix)


@pytest.mark.parametrize("pixels", [b"\\\\V@:4WV.F", b"~\\wNxZ9aK]", b"(\\\\ja=9t"], ids=lambda _: "case")
def test_compressed_pixels_are_not_prose(pixels, tmp_path):
    raw = png(pixels=pixels)
    assert pixels in raw  # Stored deflate reproduces the reported printable runs.
    assert not scan(raw, tmp_path)


@pytest.mark.parametrize("metadata", [
    chunk(b"tEXt", b"Comment\x00" + PRIVATE),
    chunk(b"zTXt", b"Comment\x00\x00" + zlib.compress(PRIVATE)),
    chunk(b"iTXt", b"Comment\x00\x00\x00en\x00Title\x00" + PRIVATE),
    chunk(b"iTXt", b"Comment\x00\x01\x00en\x00Title\x00" + zlib.compress(PRIVATE)),
    chunk(b"iTXt", b"Comment\x00\x00\x00en\x00" + PRIVATE + b"\x00Public text"),
    chunk(b"iCCP", b"Profile\x00\x00" + zlib.compress(PRIVATE)),
    chunk(b"raNd", PRIVATE),
    chunk(b"tEXt", b"Comment\x00{\"source_type\":\"local_reference\",\"url\":\"file:///private/report\"}"),
    chunk(b"zTXt", b"Comment\x00\x00" + zlib.compress(b"C%3A%5CUsers%5Coperator%5Cprivate.json")),
], ids=lambda _: "case")
def test_private_metadata_is_rejected(metadata, tmp_path):
    assert scan(png(metadata), tmp_path)


@pytest.mark.parametrize("metadata", [
    chunk(b"tEXt", b"Comment\x00Public assessment image"),
    chunk(b"zTXt", b"Comment\x00\x00" + zlib.compress(b"Public assessment image")),
    chunk(b"iTXt", b"Comment\x00\x00\x00en\x00Title\x00Public assessment image"),
    chunk(b"iTXt", b"Comment\x00\x01\x00en\x00Title\x00" + zlib.compress("Public image \u2014 verified".encode())),
    chunk(b"raNd", b"Public metadata"),
], ids=lambda _: "case")
def test_public_metadata_is_accepted(metadata, tmp_path):
    assert not scan(png(metadata), tmp_path)


def test_split_image_stream_palette_interlace_and_post_image_metadata(tmp_path):
    stream = zlib.compress(b"\x00\x00")
    raw = SIGNATURE + header() + chunk(b"IDAT", stream[:3]) + chunk(b"IDAT", b"") + chunk(b"IDAT", stream[3:]) + chunk(b"tEXt", b"Comment\x00Public image") + chunk(b"IEND", b"")
    assert not scan(raw, tmp_path)
    palette = SIGNATURE + header(color=3) + chunk(b"PLTE", b"\x00\x00\x00") + chunk(b"IDAT", stream) + chunk(b"IEND", b"")
    assert not scan(palette, tmp_path)
    assert not scan(png(interlace=1), tmp_path)


@pytest.mark.parametrize("raw", [
    SIGNATURE,
    b"not a PNG",
    png()[:-1],
    png() + PRIVATE,
    png() + chunk(b"tEXt", b"Comment\x00" + PRIVATE),
    png() + png(),
    SIGNATURE + chunk(b"IDAT", zlib.compress(b"\x00\x00")) + header() + chunk(b"IEND", b""),
    SIGNATURE + header() + header() + chunk(b"IDAT", zlib.compress(b"\x00\x00")) + chunk(b"IEND", b""),
    SIGNATURE + header() + chunk(b"IDAT", zlib.compress(b"\x00\x00")) + chunk(b"tEXt", b"Comment\x00Public image") + chunk(b"IDAT", b"") + chunk(b"IEND", b""),
    SIGNATURE + header() + chunk(b"IDAT", b"not compressed pixels") + chunk(b"IEND", b""),
    SIGNATURE + header() + chunk(b"IDAT", zlib.compress(b"\x00\x00") + PRIVATE) + chunk(b"IEND", b""),
    SIGNATURE + header() + chunk(b"IDAT", zlib.compress(b"\x00\x00") + zlib.compress(PRIVATE)) + chunk(b"IEND", b""),
    SIGNATURE + header() + chunk(b"IDAT", zlib.compress(b"\x05\x00")) + chunk(b"IEND", b""),
    SIGNATURE + header() + chunk(b"IDAT", zlib.compress(b"\x00\x00extra pixels")) + chunk(b"IEND", b""),
    SIGNATURE + header(0) + chunk(b"IDAT", zlib.compress(b"\x00\x00")) + chunk(b"IEND", b""),
    SIGNATURE + header(0x7fffffff, 0x7fffffff) + chunk(b"IDAT", zlib.compress(b"\x00\x00")) + chunk(b"IEND", b""),
    SIGNATURE + header(color=3) + chunk(b"IDAT", zlib.compress(b"\x00\x00")) + chunk(b"IEND", b""),
    SIGNATURE + header() + chunk(b"IEND", b""),
    png(chunk(b"ABCD", b"unknown critical")),
    png(chunk(b"text", b"invalid reserved bit")),
    png(chunk(b"tEXt", b"no separator")),
    png(chunk(b"zTXt", b"Comment\x00\x01" + zlib.compress(b"Public text"))),
    png(chunk(b"zTXt", b"Comment\x00\x00" + zlib.compress(b"Public text") + PRIVATE)),
    png(chunk(b"iTXt", b"Comment\x00\x01\x00en\x00Title\x00broken compressed data")),
    png(chunk(b"iTXt", b"Comment\x00\x00\x00en\x00Title\x00\xff")),
    png(chunk(b"gAMA", b"bad length")),
    png(chunk(b"zTXt", b"Comment\x00\x00" + zlib.compress(b"x" * (8 * 1024 * 1024 + 1)))),
], ids=lambda _: "case")
def test_malformed_pngs_fail_closed(raw, tmp_path):
    assert scan(raw, tmp_path)


def test_bad_crc_oversized_length_and_metadata_order_fail_closed(tmp_path):
    raw = bytearray(png())
    raw[29] ^= 1
    assert scan(bytes(raw), tmp_path)
    raw = bytearray(png())
    raw[8:12] = b"\x7f\xff\xff\xff"
    assert scan(bytes(raw), tmp_path)
    stream = chunk(b"IDAT", zlib.compress(b"\x00\x00"))
    for kind, content in [(b"PLTE", b"\x00\x00\x00"), (b"pHYs", b"\x00" * 9), (b"gAMA", b"\x00\x00\xb1\x8f")]:
        assert scan(SIGNATURE + header() + stream + chunk(kind, content) + chunk(b"IEND", b""), tmp_path)


def test_other_binary_scans_still_reject_private_content(tmp_path):
    for suffix in (".jpg", ".pdf", ".woff2"):
        assert scan(b"binary\x00" + PRIVATE, tmp_path, suffix)
