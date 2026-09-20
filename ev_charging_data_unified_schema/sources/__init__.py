"""One loader per approved source (docs/BRIEF.md § 4). Each implements
``interfaces.SourceLoader``: download the published files politely, read one file into a
string-typed frame with the publisher's column names, nothing else."""

from __future__ import annotations

from ev_charging_data_unified_schema.interfaces import SourceLoader
from ev_charging_data_unified_schema.sources import boulder, cary, dft_2017

LOADERS: dict[str, SourceLoader] = {
    boulder.LOADER.SOURCE: boulder.LOADER,
    cary.LOADER.SOURCE: cary.LOADER,
    dft_2017.LOADER.SOURCE: dft_2017.LOADER,
}
