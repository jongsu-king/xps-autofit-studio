# Examples

`xps-autofit synth --out examples/data` writes synthetic spectra with known truth:

| File | Content | Format features |
|------|---------|-----------------|
| `p3ht_fresh_S2p.csv` | one S 2p doublet (thiophene) | CSV with header |
| `p3ht_aged_S2p.csv` | thiophene + oxidised sulfur doublets | CSV with header |
| `p3ht_C1s.csv` | four overlapping C 1s components | CSV with header |
| `cu2o_Cu2p3.txt` | Cu(I)/Cu(0), Cu(II) and two broad satellites | tab-separated, descending axis |
| `p3ht_fresh_S2p_kinetic.csv` | same as fresh S 2p | kinetic-energy column |
| `p3ht_aged_multi.vms` | S 2p and C 1s blocks | VAMAS, kinetic-energy abscissa |
| `truth.json` | generating parameters of every file | |

Then:

```bash
xps-autofit fit examples/data/p3ht_aged_multi.vms --recipe p3ht --output examples/data/p3ht_out
xps-autofit fit examples/data/cu2o_Cu2p3.txt --recipe cu2o --output examples/data/cu_out
xps-autofit batch examples/data --recipe p3ht --region "S 2p" --output examples/data/batch_out --formats csv,xlsx,json,png
```

`python examples/compare_with_truth.py examples/data examples/data/batch_out`
prints the recovered values next to the generating ones.

`QT_QPA_PLATFORM=offscreen python examples/make_screenshots.py docs/images`
renders the desktop-application screenshots used in the documentation without a
display (synthetic data, built-in recipes, `MainWindow(synchronous_jobs=True)`).
