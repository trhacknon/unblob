from pathlib import Path
from typing import List

import attr
import pytest

from unblob.models import UnknownChunk, ValidChunk
from unblob.processing import (
    ExtractionConfig,
    calculate_buffer_size,
    calculate_entropy,
    calculate_unknown_chunks,
    draw_entropy_plot,
    remove_inner_chunks,
)


def assert_same_chunks(expected, actual, explanation=None):
    """An assert, that ignores the chunk.id-s"""

    assert len(expected) == len(actual), explanation
    for i, (e, a) in enumerate(zip(expected, actual)):
        assert attr.evolve(e, id="") == attr.evolve(a, id=""), explanation


@pytest.mark.parametrize(
    "chunks, expected, explanation",
    [
        ([], [], "Empty list as chunks (No chunk found)"),
        (
            [
                ValidChunk(1, 2),
            ],
            [ValidChunk(1, 2)],
            "Only one chunk",
        ),
        (
            [
                ValidChunk(0, 5),
                ValidChunk(1, 2),
            ],
            [ValidChunk(0, 5)],
            "One chunk within another",
        ),
        (
            [
                ValidChunk(10, 20),
                ValidChunk(11, 13),
                ValidChunk(14, 19),
            ],
            [ValidChunk(10, 20)],
            "Multiple chunks within 1 outer chunk",
        ),
        (
            [
                ValidChunk(11, 13),
                ValidChunk(10, 20),
                ValidChunk(14, 19),
            ],
            [ValidChunk(10, 20)],
            "Multiple chunks within 1 outer chunk, in different order",
        ),
        (
            [
                ValidChunk(1, 5),
                ValidChunk(6, 10),
            ],
            [ValidChunk(1, 5), ValidChunk(6, 10)],
            "Multiple outer chunks",
        ),
        (
            [
                ValidChunk(1, 5),
                ValidChunk(2, 3),
                ValidChunk(6, 10),
                ValidChunk(7, 8),
            ],
            [ValidChunk(1, 5), ValidChunk(6, 10)],
            "Multiple outer chunks, with chunks inside",
        ),
        (
            [ValidChunk(10, 50), ValidChunk(40, 80), ValidChunk(70, 90)],
            [ValidChunk(10, 50), ValidChunk(40, 80), ValidChunk(70, 90)],
            "Overlapping chunks",
        ),
    ],
)
def test_remove_inner_chunks(
    chunks: List[ValidChunk], expected: List[ValidChunk], explanation: str
):
    assert_same_chunks(expected, remove_inner_chunks(chunks), explanation)


@pytest.mark.parametrize(
    "chunks, file_size, expected",
    [
        ([], 0, []),
        ([], 10, []),
        ([ValidChunk(0x0, 0x5)], 5, []),
        ([ValidChunk(0x0, 0x5), ValidChunk(0x5, 0xA)], 10, []),
        ([ValidChunk(0x0, 0x5), ValidChunk(0x5, 0xA)], 12, [UnknownChunk(0xA, 0xC)]),
        ([ValidChunk(0x3, 0x5)], 5, [UnknownChunk(0x0, 0x3)]),
        ([ValidChunk(0x0, 0x5), ValidChunk(0x7, 0xA)], 10, [UnknownChunk(0x5, 0x7)]),
        (
            [ValidChunk(0x8, 0xA), ValidChunk(0x0, 0x5), ValidChunk(0xF, 0x14)],
            20,
            [UnknownChunk(0x5, 0x8), UnknownChunk(0xA, 0xF)],
        ),
        pytest.param(
            [ValidChunk(10, 50), ValidChunk(40, 80), ValidChunk(70, 90)],
            100,
            [UnknownChunk(0, 10), UnknownChunk(90, 100)],
            id="overlapping-input-chunks",
        ),
        pytest.param(
            [ValidChunk(10, 50), ValidChunk(30, 40), ValidChunk(60, 70)],
            100,
            [UnknownChunk(0, 10), UnknownChunk(50, 60), UnknownChunk(70, 100)],
            id="overlapping-internal-chunk",
        ),
    ],
)
def test_calculate_unknown_chunks(
    chunks: List[ValidChunk], file_size: int, expected: List[UnknownChunk]
):
    assert_same_chunks(expected, calculate_unknown_chunks(chunks, file_size))


@pytest.mark.parametrize(
    "file_size, chunk_count, min_limit, max_limit, expected",
    [
        (1000, 1, 10, 100, 100),
        (1000, 10, 10, 100, 100),
        (1000, 100, 10, 100, 10),
    ],
)
def test_calculate_buffer_size(
    file_size: int, chunk_count: int, min_limit: int, max_limit: int, expected: int
):
    assert expected == calculate_buffer_size(
        file_size, chunk_count=chunk_count, min_limit=min_limit, max_limit=max_limit
    )


def test_draw_entropy_plot_error():
    with pytest.raises(TypeError):
        draw_entropy_plot([])


@pytest.mark.parametrize(
    "percentages",
    [
        pytest.param([0.0] * 100, id="zero-array"),
        pytest.param([99.99] * 100, id="99-array"),
        pytest.param([100.0] * 100, id="100-array"),
    ],
)
def test_draw_entropy_plot_no_exception(percentages: List[float]):
    assert draw_entropy_plot(percentages) is None


@pytest.mark.parametrize(
    "path, draw_plot",
    [
        pytest.param(Path("/proc/self/exe"), True, id="draw-plot"),
        pytest.param(Path("/proc/self/exe"), False, id="no-plot"),
    ],
)
def test_calculate_entropy_no_exception(path: Path, draw_plot: bool):
    assert calculate_entropy(path, draw_plot=draw_plot) is None


@pytest.mark.parametrize(
    "extract_root, path, result",
    [
        ("/extract", "firmware", "/extract/firmware_extract"),
        ("/extract", "relative/firmware", "/extract/firmware_extract"),
        ("/extract", "/extract/dir/firmware", "/extract/dir/firmware_extract"),
        (
            "/extract/dir",
            "/extract/dir/firmware",
            "/extract/dir/firmware_extract",
        ),
        ("/extract", "/some/place/else/firmware", "/extract/firmware_extract"),
        (
            "extract",
            "/some/place/else/firmware",
            str(Path(".").resolve() / "extract/firmware_extract"),
        ),
    ],
)
def test_ExtractionConfig_get_extract_dir_for(
    extract_root: str, path: str, result: str
):
    cfg = ExtractionConfig(extract_root=Path(extract_root), entropy_depth=0)
    assert cfg.get_extract_dir_for(Path(path)) == Path(result)
