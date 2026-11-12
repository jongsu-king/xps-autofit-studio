import numpy as np
import pytest

from xps_autofit.readers import read_spectra, register_reader, supported_extensions
from xps_autofit.readers.csv_reader import TextReadError, read_text
from xps_autofit.readers.vamas_reader import (
    VamasError,
    _block_name,
    parse_vamas,
    read_vamas,
    write_vamas,
)
from xps_autofit.synthetic import p3ht_s2p, synthesize


@pytest.fixture
def spec():
    return synthesize(p3ht_s2p(True), seed=2)[0]


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_csv_with_header(tmp_path, spec):
    lines = ["Binding Energy (eV),Counts"] + [
        f"{e:.3f},{int(i)}" for e, i in zip(spec.energy, spec.intensity)
    ]
    p = _write(tmp_path, "a.csv", "\n".join(lines))
    s = read_spectra(p)[0]
    assert s.intensity_unit == "counts"
    assert np.allclose(s.energy, spec.energy, atol=1e-3)
    assert s.metadata["energy_column"] == "Binding Energy (eV)"


def test_tab_descending_and_extra_columns(tmp_path, spec):
    lines = ["Binding Energy (eV)\tCounts\tBackground\tEnvelope"]
    for e, i in zip(spec.energy[::-1], spec.intensity[::-1]):
        lines.append(f"{e:.2f}\t{i:.0f}\t{i * 0.5:.1f}\t{i:.1f}")
    p = _write(tmp_path, "b.txt", "\n".join(lines))
    s = read_spectra(p)[0]
    assert np.all(np.diff(s.energy) > 0)
    assert s.history[0]["input_order"] == "descending"
    assert s.metadata["intensity_column"] == "Counts"
    assert s.intensity[-1] == spec.intensity[-1]


def test_whitespace_no_header_and_decimal_comma(tmp_path, spec):
    lines = [f"{e:.2f}   {i:.0f}" for e, i in zip(spec.energy, spec.intensity)]
    s = read_spectra(_write(tmp_path, "c.dat", "# comment\n" + "\n".join(lines)))[0]
    assert s.n == spec.n and s.intensity_unit == "counts"
    lines = [
        f"{e:.2f};{i:.1f}".replace(".", ",") for e, i in zip(spec.energy, spec.intensity + 0.5)
    ]
    s = read_spectra(_write(tmp_path, "d.csv", "E;I\n" + "\n".join(lines)))[0]
    assert s.intensity_unit == "arbitrary"
    assert s.energy[0] == pytest.approx(spec.energy[0], abs=0.01)


def test_kinetic_energy_column_converted(tmp_path, spec):
    ke = 1486.6 - spec.energy
    lines = ["Kinetic Energy (eV),Counts"] + [
        f"{e:.3f},{int(i)}" for e, i in zip(ke, spec.intensity)
    ]
    p = _write(tmp_path, "ke.csv", "\n".join(lines))
    s = read_spectra(p)[0]
    assert s.axis == "binding"
    assert np.allclose(s.energy, spec.energy, atol=1e-3)
    assert any(h["step"] == "assumed_photon_energy" for h in s.history)
    s2 = read_spectra(p, photon_energy=1253.6)[0]
    assert s2.energy[0] == pytest.approx(1253.6 - ke.max(), abs=1e-3)


def test_multiple_blocks_and_column_selection(tmp_path, spec):
    block = "\n".join(f"{e:.2f},{int(i)}" for e, i in zip(spec.energy, spec.intensity))
    text = "Region S 2p\nBE,Counts\n" + block + "\n\nRegion C 1s\nBE,Counts\n" + block
    spectra = read_spectra(_write(tmp_path, "multi.csv", text))
    assert len(spectra) == 2 and spectra[1].name.endswith("[2]")
    s = read_text(
        _write(
            tmp_path,
            "cols.csv",
            "x,y,z\n"
            + "\n".join(
                f"{e:.2f},{int(i)},{int(i) // 2}" for e, i in zip(spec.energy, spec.intensity)
            ),
        ),
        intensity_col="z",
    )
    assert s[0].intensity[0] == int(spec.intensity[0]) // 2
    with pytest.raises(TextReadError):
        read_text(_write(tmp_path, "bad.csv", "x,y\n1,2\n"))


def test_cp949_file_is_read(tmp_path, spec):
    lines = ["결합에너지,카운트"] + [
        f"{e:.2f},{int(i)}" for e, i in zip(spec.energy, spec.intensity)
    ]
    p = tmp_path / "kr.csv"
    p.write_bytes("\n".join(lines).encode("cp949"))
    s = read_spectra(p)[0]
    assert s.metadata["encoding"] == "cp949"


def test_vamas_roundtrip(tmp_path, spec):
    a = spec.copy()
    a.metadata.update({"species": "S", "transition": "2p", "sample": "P3HT"})
    b = spec.copy()
    b.name = "second"
    p = write_vamas(tmp_path / "rt.vms", [a, b], institution="inst", instrument="synthetic")
    spectra = read_spectra(p)
    assert len(spectra) == 2
    assert np.allclose(spectra[0].energy, spec.energy, atol=1e-5)
    assert np.allclose(spectra[0].intensity, spec.intensity)
    assert spectra[0].intensity_unit == "counts"
    assert spectra[0].metadata["species"] == "S" and spectra[0].metadata["transition"] == "2p"
    assert spectra[0].photon_energy == pytest.approx(1486.6)
    p2 = write_vamas(tmp_path / "ke.vms", [a], axis="kinetic")
    s = read_vamas(p2)[0]
    assert s.axis == "binding" and np.allclose(s.energy, spec.energy, atol=1e-5)
    assert any(h["step"] == "kinetic_to_binding" for h in s.history)


def test_vamas_names_do_not_repeat_the_region():
    assert _block_name("P3HT C 1s", "C", "1s") == "P3HT C 1s"
    assert _block_name("aged film, s 2P", "S", "2p") == "aged film, s 2P"
    assert _block_name("Sample 3", "Cu", "2p3/2") == "Sample 3 Cu 2p3/2"
    assert _block_name("XS 2px", "S", "2p") == "XS 2px S 2p", "only whole words count"
    assert _block_name("", "O", "1s") == "O 1s" and _block_name("Survey", "", "") == "Survey"


HAND_WRITTEN = """VAMAS Surface Chemical Analysis Standard Data Transfer Format 1988 May 4
Test lab
Spectrometer
operator
exp
1
one comment line
NORM
REGULAR
1
0
0
0
0
0
1
block one
sample one
2026
1
2
3
4
5
0
0
XPS
Al Ka
1486.6
100
0
0
0
0
FAT
20
1
4.5
0
0
0
0
0
S
2p
-1
kinetic energy
eV
1320.0
0.5
1
counts
d
pulse counting
0.1
5
0
0
0
0
0
12
1
60
10
20
30
40
50
60
50
40
30
20
10
1
end of experiment
"""


def test_hand_written_vamas(tmp_path):
    p = tmp_path / "hand.vms"
    p.write_text(HAND_WRITTEN)
    header, blocks = parse_vamas(HAND_WRITTEN)
    assert header.n_blocks == 1 and blocks[0].species == "S"
    s = read_spectra(p)[0]
    assert s.n == 12 and s.axis == "binding"
    assert s.energy[-1] == pytest.approx(1486.6 - 1320.0)
    assert s.intensity[-1] == 10.0  # first KE point becomes the last BE point
    assert s.dwell_time_s == pytest.approx(0.1) and s.n_scans == 5
    assert s.intensity_unit == "counts"


def test_vamas_errors(tmp_path):
    with pytest.raises(VamasError):
        parse_vamas("not a vamas file\n")
    bad = HAND_WRITTEN.replace("\n0\n0\n0\n0\n1\nblock one", "\n2\n1\n2\n0\n0\n0\n1\nblock one", 1)
    with pytest.raises(VamasError):
        parse_vamas(bad)


def test_registry_and_sniffing(tmp_path):
    assert ".vms" in supported_extensions()
    p = tmp_path / "noext"
    p.write_text(HAND_WRITTEN)
    assert read_spectra(p)[0].n == 12
    called = {}

    def fake(path, **kw):
        called["path"] = path
        return []

    register_reader(".spe", fake)
    q = tmp_path / "x.spe"
    q.write_text("")
    assert read_spectra(q) == [] and called["path"] == q
    with pytest.raises(FileNotFoundError):
        read_spectra(tmp_path / "missing.csv")
