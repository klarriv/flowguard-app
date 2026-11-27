"""Display formatting on the Cyclone page: efficiencies never round to 100 %."""
import pytest

from utils.cyclone_format import efficiency_pct, sci


@pytest.mark.parametrize("eta, text", [
    (0.9999588276768394, "99.9959 %"),   # 40-HE case file
    (0.9840930948200515, "98.41 %"),
    (0.5, "50.00 %"),
    (0.0, "0.00 %"),
    (1.0, "100 %"),
    (1 - 1e-9, "99.99999990 %"),
    (0.99999996, "99.9999960 %"),
])
def test_efficiency_pct(eta, text):
    assert efficiency_pct(eta) == text


def test_efficiency_never_shows_100_unless_exact():
    for k in range(1, 12):
        assert not efficiency_pct(1 - 10 ** -k).startswith("100")


@pytest.mark.parametrize("value, text", [
    (4.117232316058761e-05, "4.12 × 10⁻⁵"),
    (9.996e-5, "1.00 × 10⁻⁴"),
    (0.0123, "1.23 × 10⁻²"),
    (2.5, "2.50"),
    (12345.0, "1.23 × 10⁴"),
    (0.0, "0"),
])
def test_sci(value, text):
    assert sci(value) == text
