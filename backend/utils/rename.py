import os

def rename_dataset_images(folder_path="Dataset"):
    # Check if the folder exists
    if not os.path.exists(folder_path):
        print(f"Error: Folder '{folder_path}' does not exist.")
        return

    # Supported image formats
    valid_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff')
    
    # Retrieve and sort all valid image files
    files = [f for f in os.listdir(folder_path) if f.lower().endswith(valid_extensions)]
    files.sort()  # Sorts alphabetically to maintain consistent ordering
    
    if not files:
        print(f"No valid image files found in '{folder_path}'.")
        return

    print(f"Found {len(files)} image(s) in '{folder_path}'. Starting rename...\n")

    # Pass 1: Rename files to a temporary name to avoid filename collisions
    temp_records = []
    for index, filename in enumerate(files, start=1):
        ext = os.path.splitext(filename)[1].lower()
        old_path = os.path.join(folder_path, filename)
        
        temp_name = f"__temp_rename_{index}__{ext}"
        temp_path = os.path.join(folder_path, temp_name)
        
        os.rename(old_path, temp_path)
        temp_records.append((temp_path, ext, filename))

    # Pass 2: Rename from temporary names to final target names (Image1, Image2, ...)
    for index, (temp_path, ext, original_filename) in enumerate(temp_records, start=1):
        final_name = f"Image{index}{ext}"
        final_path = os.path.join(folder_path, final_name)
        
        os.rename(temp_path, final_path)
        print(f"Renamed: {original_filename} -> {final_name}")

    print(f"\nSuccessfully renamed {len(files)} files in '{folder_path}'.")

if __name__ == "__main__":
    rename_dataset_images()