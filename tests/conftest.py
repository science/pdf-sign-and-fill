import os
import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")


@pytest.fixture
def simple_pdf():
    return os.path.join(FIXTURES_DIR, "simple.pdf")


@pytest.fixture
def medium_pdf():
    return os.path.join(FIXTURES_DIR, "medium.pdf")


@pytest.fixture
def signature_png():
    return os.path.join(FIXTURES_DIR, "signature.png")


@pytest.fixture
def default_font():
    return "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"


@pytest.fixture
def tmp_output(tmp_path):
    return str(tmp_path / "output.pdf")
