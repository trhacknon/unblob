import pytest
from pytest import approx

from unblob import math

@pytest.mark.parametrize(
    "data, entropy",
    (
        pytest.param(b"", 0, id="empty"),
        pytest.param(b"\x00", 0, id="0 bit"),
        pytest.param(b"\x01\x01\x00\x00", 1.0, id="1 bit small"),
        pytest.param(b"\x01\x01\x00\x00" * 1000, 1.0, id="1 bit large"),
        pytest.param(b"\x00\x01\x02\x03", 2.0, id="2 bits"),
    ),
)
def test_shannon_entropy(data, entropy):
    assert math.shannon_entropy(data) == approx(entropy)
