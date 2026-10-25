# torch and xgboost each bundle their own OpenMP runtime, and on macOS the
# two do not coexist in one process: torch loaded first makes xgboost
# segfault on its first fit, and xgboost loaded first makes torch's
# multi-threaded kernels deadlock. Loading xgboost first and keeping torch
# on one thread avoids both. Every training and evaluation entry point
# imports this package, so this is the one place the order is fixed
# (DECISIONS.md 2026-10-26, "OpenMP runtimes on macOS"). Linux, and the live
# service (which never installs torch), are unaffected.
import sys

import xgboost  # noqa: F401

if sys.platform == "darwin":
    try:
        import torch
    except ImportError:
        pass
    else:
        torch.set_num_threads(1)
