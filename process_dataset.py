import os
import pandas as pd
from ocr_engine import process_pipeline


def process_dataset(
    dataset_dir,
    output_csv,
    crop_half,
    x_tolerance,
):
    """
    Iterates through all images in `dataset_dir`, processes them via the OCR
    engine, and exports the extracted data to `output_csv`.

    Parameters
    ----------
    dataset_dir : str
        Path to the folder containing container images.
    output_csv : str
        Output CSV file path for results.
    crop_half : bool
        Passed directly to process_pipeline().
        True  → Dataset2 / real-app mode  : right-half scan (current engine logic).
        False → Dataset  / training mode  : full-image scan, first-letter anchor.
    x_tolerance : int
        Pixel tolerance for column grouping in OCR pass 2.
        Dataset  uses 150 (wider — varied image conditions).
        Dataset2 uses  50 (tighter — controlled real-app conditions).
    """
    if not os.path.exists(dataset_dir):
        print(f"[SKIP] Directory '{dataset_dir}' does not exist.")
        return

    image_files = sorted([
        f for f in os.listdir(dataset_dir)
        if f.lower().endswith(('.png', '.jpg', '.jpeg'))
    ])

    if not image_files:
        print(f"[SKIP] No image files found in '{dataset_dir}'.")
        return

    results = []
    total = len(image_files)
    mode_label = "crop_half=True (right-half, real-app)" if crop_half else "crop_half=False (full-image, training)"
    print(f"\n{'='*65}")
    print(f"  Processing : {dataset_dir}")
    print(f"  Mode       : {mode_label}")
    print(f"  Images     : {total}")
    print(f"  Output CSV : {output_csv}")
    print(f"{'='*65}")

    for idx, filename in enumerate(image_files, start=1):
        filepath = os.path.join(dataset_dir, filename)
        print(f"\n[{idx}/{total}] {filename}")

        try:
            with open(filepath, 'rb') as f:
                image_bytes = f.read()

            # The annotated image is not needed for CSV generation
            _, extracted_data = process_pipeline(
                image_bytes,
                x_tolerance=x_tolerance,
                crop_half=crop_half,
            )

            results.append({
                "Filename":       filename,
                "Serial Number":  extracted_data.get("Serial Number :", ""),
                "Check Number":   extracted_data.get("Check Number :", ""),
                "Nomor Container": extracted_data.get("Nomor Container :", ""),
                "Grade":          extracted_data.get("Grade", ""),
            })

        except Exception as e:
            print(f"  [ERROR] {e}")
            results.append({
                "Filename":        filename,
                "Serial Number":   "Error",
                "Check Number":    "Error",
                "Nomor Container": "Error",
                "Grade":           f"Error: {e}",
            })

    df = pd.DataFrame(results)
    df.to_csv(output_csv, index=False)
    print(f"\n[DONE] {total} images processed — results saved to '{output_csv}'")


if __name__ == "__main__":
    # ── Dataset: full-image scan, letters + numbers across all conditions ──────
    # crop_half=False : Pass 1 scans the FULL image (no half-split).
    # x_tolerance=150 : wider grouping to handle varied image conditions.
    process_dataset(
        dataset_dir="Dataset",
        output_csv="dataset_results.csv",
        crop_half=False,
        x_tolerance=150,
    )

    # ── Dataset2: right-half scan, mirrors real deployment conditions ──────────
    # crop_half=True  : EXACT current OCR engine logic (right half → first letter → read).
    # x_tolerance=50  : tighter grouping for controlled real-app images.
    process_dataset(
        dataset_dir="Dataset2",
        output_csv="dataset2_results.csv",
        crop_half=True,
        x_tolerance=50,
    )
