"""
Orchestrator: run the Ottawa heat island pipeline end to end.

By default this runs steps 2 to 5 using the scene list in
outputs/approved_scenes.json.

  python scripts/run_all.py                    # steps 2, 3, 4, 5
  python scripts/run_all.py --with-selection   # also run step 1 first

Review points: the scene list after step 1 and the composite sanity check
after step 2. Inspect the outputs between steps, or run straight through.
"""

import argparse
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def run(module_file: str):
    print(f"\n{'='*60}\nRUNNING {module_file}\n{'='*60}")
    runpy.run_path(str(HERE / module_file), run_name="__main__")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-selection", action="store_true",
                    help="also run Step 1 scene selection first")
    args = ap.parse_args()

    if args.with_selection:
        run("step1_scene_selection.py")
    run("step2_download_process.py")
    run("step3_aggregate.py")
    run("step4_qc_viz_methods.py")
    run("step5_heatwave_panel.py")
    print("\nPipeline complete. See the outputs folder.")


if __name__ == "__main__":
    main()
