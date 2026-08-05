import os
import pandas as pd
from ocr_engine import process_pipeline

def process_dataset(dataset_dir="Dataset", output_csv="dataset_results.csv"):
    """
    Iterates through all images in the Dataset folder, processes them via the OCR engine,
    and exports the extracted data to a CSV file for automated testing.
    """
    if not os.path.exists(dataset_dir):
        print(f"Directory '{dataset_dir}' does not exist. Creating it.")
        os.makedirs(dataset_dir)
        print(f"Please place some container images in the '{dataset_dir}' folder and run again.")
        return
        
    image_files = [f for f in os.listdir(dataset_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    
    if not image_files:
        print(f"No image files found in '{dataset_dir}'.")
        return
        
    results = []
    print(f"Starting OCR Batch Processing for {len(image_files)} images...")
    
    for filename in image_files:
        filepath = os.path.join(dataset_dir, filename)
        print(f"Processing {filename}...")
        
        try:
            with open(filepath, 'rb') as f:
                image_bytes = f.read()
                
            # Process the image. We don't need the annotated image for the CSV
            _, extracted_data = process_pipeline(image_bytes, x_tolerance=150)
            
            results.append({
                "Filename": filename,
                "Serial Number": extracted_data.get("Serial Number :", ""),
                "Check Number": extracted_data.get("Check Number :", ""),
                "Nomor Container": extracted_data.get("Nomor Container :", ""),
                "Grade": extracted_data.get("Grade", "")
            })
        except Exception as e:
            print(f"Error processing {filename}: {str(e)}")
            results.append({
                "Filename": filename,
                "Serial Number": "Error",
                "Check Number": "Error",
                "Nomor Container": "Error",
                "Grade": f"Error: {str(e)}"
            })
            
    # Export the collected data to a pandas DataFrame and save as CSV
    df = pd.DataFrame(results)
    df.to_csv(output_csv, index=False)
    print(f"\nProcessing complete! Results successfully saved to {output_csv}")

if __name__ == "__main__":
    process_dataset()
