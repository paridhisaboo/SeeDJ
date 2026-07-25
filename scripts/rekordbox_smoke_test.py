"""
Quick diagnostic: can we open your Rekordbox library, and does ANLZ parsing
work on a real track from it? Run this before trying to run the full app —
it's much faster to debug here than through the FastAPI startup logs.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO)

from app.rekordbox.analysis import load_analysis  # noqa: E402
from app.rekordbox.library import RekordboxLibrary  # noqa: E402


def main() -> None:
    print("Opening Rekordbox library...")
    try:
        library = RekordboxLibrary()
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAILED to open library: {exc}")
        print(
            "\nIf this is a SQLCipher/key error: this happens after some Rekordbox "
            "updates break pyrekordbox's key extraction. Check "
            "https://github.com/dylanljones/pyrekordbox/discussions for a fix, "
            "or use the XML fallback (see README)."
        )
        sys.exit(1)

    print(f"Opened via: {library.source}")

    count = 0
    tracks_with_analysis = []
    for track in library.iter_tracks():
        count += 1
        if track.analysis_data_path:
            tracks_with_analysis.append(track)
        if count >= 50000:  # sanity guard against runaway libraries
            break

    print(f"Total tracks found: {count}")

    if not tracks_with_analysis:
        print(
            "\nNo track had an analysis_data_path populated. This can happen "
            "in XML mode (expected — XML export doesn't include this) or if "
            "your DB schema's AnalysisDataPath column has a different name "
            "on your version. Run explore_rekordbox_schema.py to check."
        )
        return

    print(f"\nTrying up to 10 tracks to find one with rich analysis data...")

    best_analysis = None
    best_track = None
    attempts = []

    for track in tracks_with_analysis[:10]:
        resolved = library.resolve_analysis_path(track)
        if resolved is None:
            attempts.append(f"  {track.title!r}: could not resolve path to a real file")
            continue
        try:
            analysis = load_analysis(resolved)
        except Exception as exc:  # noqa: BLE001
            attempts.append(f"  {track.title!r}: FAILED to parse ({exc})")
            continue

        attempts.append(
            f"  {track.title!r}: {len(analysis.beat_grid)} beat grid points, "
            f"waveform via {analysis.waveform_tag_used or 'none'}, "
            f"tags={analysis.available_tags}"
        )
        # Prefer whichever track gave us the most beat grid points as "best".
        if best_analysis is None or len(analysis.beat_grid) > len(best_analysis.beat_grid):
            best_analysis = analysis
            best_track = track

    print("\n".join(attempts))

    if best_analysis is None:
        print("\nNone of the sampled tracks parsed successfully. See failures above.")
        return

    print(f"\nBest result — {best_track.title} by {best_track.artist}:")
    print(f"  Files found: {best_analysis.files_found}")
    print(f"  Available tags (merged across DAT/EXT/2EX): {best_analysis.available_tags}")
    print(f"  Beat grid: {len(best_analysis.beat_grid)} points via {best_analysis.beat_grid_tag_used}")
    if best_analysis.beat_grid:
        p = best_analysis.beat_grid[0]
        print(f"    First point: beat {p.beat_number} @ {p.time_seconds:.2f}s, {p.bpm} BPM")
    print(f"  Waveform: tag {best_analysis.waveform_tag_used or 'NONE FOUND'}")
    if best_analysis.waveform_data is not None:
        print(f"  Waveform data type: {type(best_analysis.waveform_data)}")

    print(
        "\nDone. If this all looks populated, Stage 1's Rekordbox side is "
        "fully verified — send me this output."
    )


if __name__ == "__main__":
    main()