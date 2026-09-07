"""Allow `python -m long_horizon_swe` as well as the installed console script."""

from long_horizon_swe.cli.main import main

raise SystemExit(main())
